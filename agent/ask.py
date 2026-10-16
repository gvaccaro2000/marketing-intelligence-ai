"""Ask the Dice Kingdom analytics agent a question.

    python agent/ask.py "Why did Android D1 retention drop in late July?"

Prints the answer, every SQL query that ran, and the sources retrieved.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.core import AgentResult, DiceAgent  # noqa: E402


def render(r: AgentResult) -> str:
    out = ["=" * 80, "ANSWER", "=" * 80, r.answer, ""]
    out += ["=" * 80, f"SQL RUN ({len(r.sql)})", "=" * 80]
    for i, q in enumerate(r.sql, 1):
        status = f"ERROR: {q['error']}" if q["error"] else (
            f"{q['rows']} rows" + (" (truncated)" if q["truncated"] else ""))
        out += [f"-- [{i}] {status}", q["query"], ""]
    if not r.sql:
        out.append("(none)\n")
    out += ["=" * 80, f"SOURCES RETRIEVED ({len(r.sources)} searches)", "=" * 80]
    for s in r.sources:
        filters = ", ".join(f"{k}={s[k]}" for k in ("source", "after") if s[k])
        out.append(f'search: "{s["query"]}"' + (f" ({filters})" if filters else ""))
        for h in s["hits"]:
            flag = " [DEPRECATED]" if h["deprecated"] else (" [draft]" if h["status"] == "draft" else "")
            out.append(f"  {h['score']:.4f}  {h['citation']}{flag}  ({h['path']})")
    if not r.sources:
        out.append("(none)")
    u = r.usage
    out += ["", f"tool calls: {r.tool_calls} | tokens in {u['input']:,} + cache read "
                f"{u['cache_read']:,} / write {u['cache_write']:,}, out {u['output']:,} | "
                f"est. cost ${r.cost_usd:.4f}"]
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    args = p.parse_args()
    print(render(DiceAgent().ask(args.question)))


if __name__ == "__main__":
    main()
