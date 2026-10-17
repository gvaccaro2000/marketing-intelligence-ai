"""Hybrid retriever over the Chroma index: vector similarity + BM25, fused with RRF."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from rank_bm25 import BM25Okapi

from agent import config

STOPWORDS = set(
    "a an and are as at be by did do does for from had has have how i in is it its of on or "
    "our so that the their them then there these this to was we were what when where which "
    "who why will with you".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; snake_case ids are kept whole *and* split into parts."""
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9_.\-]+", text.lower()):
        tok = tok.strip(".-")
        if not tok or tok in STOPWORDS:
            continue
        out.append(tok)
        if "_" in tok or "-" in tok:
            out += [p for p in re.split(r"[_\-]", tok) if p and p not in STOPWORDS]
    return out


@dataclass
class Hit:
    id: str
    text: str
    meta: dict
    score: float = 0.0
    vector_rank: int | None = None
    bm25_rank: int | None = None

    @property
    def citation(self) -> str:
        return self.meta["citation"]


class HybridRetriever:
    def __init__(self) -> None:
        from agent.rag.ingest import get_client, get_embedder

        try:
            self.col = get_client().get_collection(config.COLLECTION)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "Knowledge index not found. Build it first: python agent/rag/ingest.py"
            ) from e
        self.embedder = get_embedder()
        data = self.col.get(include=["documents", "metadatas"])
        self.ids: list[str] = data["ids"]
        self.docs: list[str] = data["documents"]
        self.metas: list[dict] = data["metadatas"]
        self.bm25 = BM25Okapi([tokenize(d) for d in self.docs])

    # ------------------------------------------------------------------ filters
    @staticmethod
    def _filter(source: str | None, after: str | None) -> tuple[dict | None, callable]:
        clauses: list[dict] = []
        if source:
            s = source.strip()
            if s.lower() in ("slack", "confluence"):
                clauses.append({"source": s.lower()})
            elif s.startswith("#"):
                clauses.append({"channel": s.lower()})
            else:
                clauses.append({"space": s})
        if after:
            d = date.fromisoformat(after)  # raises ValueError on bad input
            clauses.append({"date_end_int": {"$gte": int(d.strftime("%Y%m%d"))}})

        def keep(meta: dict) -> bool:
            for c in clauses:
                for k, v in c.items():
                    if isinstance(v, dict):
                        if meta.get(k, 0) < v["$gte"]:
                            return False
                    elif meta.get(k) != v:
                        return False
            return True

        where = None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses}
        return where, keep

    # ------------------------------------------------------------------- search
    def search(self, query: str, source: str | None = None, after: str | None = None,
               k: int = config.TOP_K) -> list[Hit]:
        where, keep = self._filter(source, after)
        n = config.CANDIDATES_PER_RETRIEVER
        hits: dict[str, Hit] = {}

        # 1) Vector similarity (Chroma, cosine) on the query embedding.
        qvec = next(iter(self.embedder.query_embed([query]))).tolist()
        allowed = sum(1 for m in self.metas if keep(m))
        if allowed:
            res = self.col.query(query_embeddings=[qvec], n_results=min(n, allowed), where=where,
                                 include=["documents", "metadatas"])
            for rank, (cid, doc, meta) in enumerate(
                zip(res["ids"][0], res["documents"][0], res["metadatas"][0])
            ):
                hits[cid] = Hit(cid, doc, meta, vector_rank=rank)

        # 2) BM25 keyword search over the same filtered corpus.
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(
            (i for i in range(len(self.ids)) if keep(self.metas[i]) and scores[i] > 0),
            key=lambda i: -scores[i],
        )[:n]
        for rank, i in enumerate(order):
            h = hits.setdefault(self.ids[i], Hit(self.ids[i], self.docs[i], self.metas[i]))
            h.bm25_rank = rank

        # 3) Reciprocal-rank fusion, then down-rank deprecated / draft pages.
        for h in hits.values():
            for r in (h.vector_rank, h.bm25_rank):
                if r is not None:
                    h.score += 1.0 / (config.RRF_K + r + 1)
            if h.meta.get("deprecated"):
                h.score *= config.DEPRECATED_WEIGHT
            elif h.meta.get("draft"):
                h.score *= config.DRAFT_WEIGHT

        # 4) De-duplicate: max N chunks per document, and drop near-copies of a chunk
        #    already selected (e.g. "Copy of ..." pages, drafts of a final page).
        ranked = sorted(hits.values(), key=lambda h: -h.score)
        out: list[Hit] = []
        per_doc: dict[str, int] = {}
        seen_tokens: list[set[str]] = []
        for h in ranked:
            doc = h.meta["doc_id"]
            if per_doc.get(doc, 0) >= config.MAX_CHUNKS_PER_DOC:
                continue
            body = set(tokenize(h.text.split("\n", 2)[-1]))
            if any(len(body & s) / max(1, len(body | s)) > 0.8 for s in seen_tokens):
                continue
            out.append(h)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            seen_tokens.append(body)
            if len(out) == k:
                break
        return out


@lru_cache(maxsize=1)
def get_retriever() -> HybridRetriever:
    return HybridRetriever()
