"""Build the knowledge-base index: knowledge/ -> chunks -> fastembed -> Chroma (agent/rag/index/).

    python agent/rag/ingest.py

Slack threads are chunked by thread (one thread = one chunk unless it is longer than
CHUNK_MAX_TOKENS, then it is split on message boundaries with a one-message overlap).
Confluence pages are chunked by heading: sections are merged up to ~CHUNK_TARGET_TOKENS
and long sections are split on paragraphs/lines, with ~CHUNK_OVERLAP_TOKENS of overlap.
Every chunk starts with a short header (source, title, section, status) so that both the
embedding and BM25 see the context, and so the LLM always sees a deprecation warning.

The index is rebuilt from scratch on every run.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent import config  # noqa: E402


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Chunk:
    text: str
    meta: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.meta['doc_id']}::{self.meta['chunk_index']}"


# --------------------------------------------------------------------------- Slack

def slack_citation(channel: str, date: str) -> str:
    return f"[Slack {channel} {date}]"


def load_slack_thread(path: Path) -> list[Chunk]:
    d = json.loads(path.read_text())
    channel = d["channel"]
    posts = d.get("messages", []) + d.get("replies", [])
    start = posts[0]["timestamp"][:10]
    end = max(p["timestamp"] for p in posts)[:10]
    slug = path.stem.split("_", 1)[1] if "_" in path.stem else path.stem
    title = slug.replace("-", " ").capitalize()
    header = f"Slack {channel} thread '{title}' started {start} by {d['author']}"
    lines = [
        f"[{p['timestamp'][:16].replace('T', ' ')}] {p['author']} ({p.get('role', '')}): {p['text']}"
        for p in posts
    ]

    # Group messages into windows <= CHUNK_MAX_TOKENS; overlap one message.
    windows: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        if cur and approx_tokens(header + "\n".join(cur + [line])) > config.CHUNK_MAX_TOKENS:
            windows.append(cur)
            cur = [cur[-1]] if approx_tokens(cur[-1]) <= config.CHUNK_OVERLAP_TOKENS * 2 else []
        cur.append(line)
    windows.append(cur)

    base = {
        "source": "slack",
        "channel": channel,
        "space": "",
        "title": title,
        "author": d["author"],
        "date": start,
        "date_end": end,
        "date_int": int(start.replace("-", "")),
        "date_end_int": int(end.replace("-", "")),
        "status": "slack",
        "deprecated": False,
        "draft": False,
        "path": str(path.relative_to(config.REPO_ROOT)),
        "doc_id": d["id"],
        "citation": slack_citation(channel, start),
    }
    chunks = []
    for i, w in enumerate(windows):
        part = f" (part {i + 1}/{len(windows)})" if len(windows) > 1 else ""
        chunks.append(Chunk(f"{header}{part}\n" + "\n".join(w), {**base, "chunk_index": i}))
    return chunks


# ---------------------------------------------------------------------- Confluence

FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def split_sections(body: str) -> list[tuple[str, str]]:
    """Return [(breadcrumb, text)] split on markdown headings (ignoring code fences)."""
    sections: list[tuple[str, list[str]]] = []
    stack: list[tuple[int, str]] = []
    cur: list[str] = []
    crumb = ""
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else HEADING.match(line)
        if m:
            if "".join(cur).strip():
                sections.append((crumb, cur))
            level, name = len(m.group(1)), m.group(2).strip()
            stack = [s for s in stack if s[0] < level] + [(level, name)]
            crumb = " > ".join(s[1] for s in stack)
            cur = [line]
        else:
            cur.append(line)
    if "".join(cur).strip():
        sections.append((crumb, cur))
    return [(c, "\n".join(lines).strip()) for c, lines in sections]


def split_long(text: str, limit: int) -> list[str]:
    """Split text on blank lines, then on lines, so each piece is <= limit tokens."""
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        if approx_tokens(para) <= limit:
            pieces.append(para)
            continue
        buf: list[str] = []
        for line in para.splitlines():
            if buf and approx_tokens("\n".join(buf + [line])) > limit:
                pieces.append("\n".join(buf))
                buf = []
            buf.append(line)
        if buf:
            pieces.append("\n".join(buf))
    return pieces


def tail_overlap(text: str) -> str:
    """Last whole lines of text totalling <= CHUNK_OVERLAP_TOKENS."""
    out: list[str] = []
    for line in reversed(text.splitlines()):
        if approx_tokens("\n".join([line] + out)) > config.CHUNK_OVERLAP_TOKENS:
            break
        out.insert(0, line)
    return "\n".join(out)


def load_confluence_page(path: Path) -> list[Chunk]:
    raw = path.read_text()
    m = FRONT_MATTER.match(raw)
    fm = yaml.safe_load(m.group(1)) if m else {}
    body = raw[m.end():] if m else raw
    title = str(fm.get("title", path.stem))
    status = str(fm.get("status", "unknown")).lower()
    date = str(fm.get("last_updated", ""))
    deprecated = (
        status == "deprecated"
        or bool(fm.get("superseded_by"))
        or "DEPRECATED" in body[:600]
    )
    draft = status == "draft"
    flag = " [DEPRECATED - do not use]" if deprecated else (" [DRAFT]" if draft else "")
    superseded = f"; superseded by {fm['superseded_by']}" if fm.get("superseded_by") else ""

    def header(crumb: str) -> str:
        return (
            f"Confluence page '{title}'{flag} (space: {fm.get('space', '')}, status: {status}, "
            f"last updated {date}{superseded})\nSection: {crumb or title}"
        )

    # Pieces = (breadcrumb, text) no longer than the budget left after the header.
    # The section line is capped at 120 chars (~30 tokens), hence header("x" * 120).
    budget = config.CHUNK_MAX_TOKENS - approx_tokens(header("x" * 120)) - config.CHUNK_OVERLAP_TOKENS
    pieces: list[tuple[str, str]] = []
    for crumb, text in split_sections(body):
        for p in split_long(text, budget):
            pieces.append((crumb, p))

    # Greedily merge consecutive pieces up to the target size.
    groups: list[tuple[list[str], list[str]]] = []  # (crumbs, texts)
    for crumb, text in pieces:
        if groups:
            crumbs, texts = groups[-1]
            size = approx_tokens("\n\n".join(texts + [text]))
            if size <= config.CHUNK_TARGET_TOKENS or (
                approx_tokens("\n\n".join(texts)) < config.CHUNK_MIN_TOKENS and size <= budget
            ):
                texts.append(text)
                if crumb not in crumbs:
                    crumbs.append(crumb)
                continue
        groups.append(([crumb], [text]))

    base = {
        "source": "confluence",
        "channel": "",
        "space": str(fm.get("space", "")),
        "title": title,
        "author": str(fm.get("owner", "")),
        "date": date,
        "date_end": date,
        "date_int": int(date.replace("-", "")) if date else 0,
        "date_end_int": int(date.replace("-", "")) if date else 0,
        "status": status,
        "deprecated": deprecated,
        "draft": draft,
        "path": str(path.relative_to(config.REPO_ROOT)),
        "doc_id": f"confluence_{path.stem}",
        "citation": f"[Confluence: {title}]",
    }
    chunks: list[Chunk] = []
    prev_text = ""
    for i, (crumbs, texts) in enumerate(groups):
        content = "\n\n".join(texts)
        overlap = tail_overlap(prev_text) if prev_text else ""
        leaves = list(dict.fromkeys(c.split(" > ")[-1] for c in crumbs if c))
        crumb = (crumbs[0] if len(leaves) == 1 else ", ".join(leaves))[:120]
        text = header(crumb) + "\n" + (f"(...) {overlap}\n\n" if overlap else "") + content
        chunks.append(Chunk(text, {**base, "chunk_index": i, "section": crumb}))
        prev_text = content
    return chunks


# --------------------------------------------------------------------------- main

def load_all() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted((config.KNOWLEDGE_DIR / "slack").glob("*/*.json")):
        chunks += load_slack_thread(path)
    for path in sorted((config.KNOWLEDGE_DIR / "confluence").glob("*.md")):
        chunks += load_confluence_page(path)
    return chunks


def get_embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.MODEL_CACHE_DIR))


def get_client():
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(config.INDEX_DIR), settings=Settings(anonymized_telemetry=False)
    )


def main() -> None:
    chunks = load_all()
    for c in chunks:
        c.meta.setdefault("section", "")

    # Rebuild: wipe the Chroma store but keep the downloaded model weights.
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    for p in config.INDEX_DIR.iterdir():
        if p != config.MODEL_CACHE_DIR:
            shutil.rmtree(p) if p.is_dir() else p.unlink()

    embedder = get_embedder()
    vectors = [v.tolist() for v in embedder.passage_embed([c.text for c in chunks])]

    client = get_client()
    col = client.create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})
    col.add(
        ids=[c.id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[c.meta for c in chunks],
        embeddings=vectors,
    )

    docs = {c.meta["doc_id"]: c.meta for c in chunks}
    by_source = Counter(c.meta["source"] for c in chunks)
    docs_by_source = Counter(m["source"] for m in docs.values())
    sizes = [approx_tokens(c.text) for c in chunks]
    print(f"Indexed {len(chunks)} chunks from {len(docs)} documents into {config.INDEX_DIR}")
    for src in ("slack", "confluence"):
        print(f"  {src:<10} {docs_by_source[src]:>3} docs -> {by_source[src]:>3} chunks")
    by_channel = Counter(c.meta["channel"] or c.meta["space"] for c in chunks)
    for k, v in sorted(by_channel.items()):
        print(f"    {k:<22} {v:>3} chunks")
    flagged = sorted({m["title"] for m in docs.values() if m["deprecated"]})
    drafts = sorted({m["title"] for m in docs.values() if m["draft"]})
    print(f"  deprecated docs: {flagged}")
    print(f"  draft docs:      {drafts}")
    print(
        f"  chunk size (approx tokens): min {min(sizes)}, median {sorted(sizes)[len(sizes) // 2]}, "
        f"max {max(sizes)}"
    )
    print(f"  embedding model: {config.EMBED_MODEL} ({len(vectors[0])} dims)")


if __name__ == "__main__":
    main()
