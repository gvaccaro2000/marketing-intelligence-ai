"""LangChain tools: knowledge search (RAG) + read-only SQL over data/marketing.duckdb.

Every tool call is also appended to TRACE so the CLI and the eval can show exactly which
SQL ran and which sources were retrieved (independently of what the model writes).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import duckdb
from langchain_core.tools import tool

from agent import config


@dataclass
class Trace:
    sql: list[dict] = field(default_factory=list)       # {query, rows, truncated, error}
    sources: list[dict] = field(default_factory=list)   # {query, filters, hits:[...]}

    def reset(self) -> None:
        self.sql.clear()
        self.sources.clear()


TRACE = Trace()


# ------------------------------------------------------------------- knowledge

@tool
def search_knowledge(query: str, source: str | None = None, after: str | None = None) -> str:
    """Search the internal knowledge base (Slack threads and Confluence pages) for context,
    explanations, incidents and decisions. Hybrid vector + keyword search; returns the top 5
    chunks, each with the citation to use in the answer.

    Args:
        query: What to look for. Include specific names (campaigns, channels, dates, versions).
        source: Optional filter: "slack", "confluence", a Slack channel such as "#ua-team",
            or a Confluence space such as "Analytics".
        after: Optional ISO date (YYYY-MM-DD); only documents with activity on/after it.
    """
    from agent.rag.retriever import get_retriever

    try:
        hits = get_retriever().search(query, source=source, after=after)
    except ValueError as e:
        return f"ERROR: bad filter ({e}). `after` must be YYYY-MM-DD."
    TRACE.sources.append({
        "query": query, "source": source, "after": after,
        "hits": [
            {"citation": h.citation, "path": h.meta["path"], "doc_id": h.meta["doc_id"],
             "chunk": h.id, "score": round(h.score, 4), "status": h.meta["status"],
             "deprecated": h.meta["deprecated"]}
            for h in hits
        ],
    })
    if not hits:
        return "No matching documents."
    blocks = []
    for i, h in enumerate(hits, 1):
        warn = ""
        if h.meta["deprecated"]:
            warn = "  !! DEPRECATED PAGE: do not use it for definitions or numbers."
        elif h.meta["draft"]:
            warn = "  ! DRAFT page: prefer the final/current version if one exists."
        blocks.append(
            f"--- Result {i}: cite as {h.citation} | status: {h.meta['status']} | "
            f"date: {h.meta['date']}{warn}\n{h.text}"
        )
    return "\n\n".join(blocks)


# ------------------------------------------------------------------------- SQL

def _connect() -> duckdb.DuckDBPyConnection:
    # read_only + no external access: no writes, no reading/writing other local files.
    return duckdb.connect(
        str(config.DB_PATH), read_only=True, config={"enable_external_access": False}
    )


LEADING_COMMENTS = re.compile(r"^\s*(?:(?:--[^\n]*(?:\n|$))|(?:/\*.*?\*/)|\s+)*", re.S)


def validate_select(sql: str) -> str | None:
    """Return an error message, or None if sql is a single SELECT / WITH statement."""
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        return f"SQL parse error: {e}"
    if len(statements) != 1:
        return f"Exactly one statement is allowed (got {len(statements)})."
    if statements[0].type != duckdb.StatementType.SELECT:
        return f"Only SELECT queries are allowed (got {statements[0].type.name})."
    first = LEADING_COMMENTS.sub("", sql, count=1).split(None, 1)
    if not first or first[0].upper().rstrip("(") not in ("SELECT", "WITH"):
        return "Query must start with SELECT or WITH."
    return None


def _format_rows(cols: list[str], rows: list[tuple]) -> str:
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.6g}"
        return "NULL" if v is None else str(v)

    lines = [" | ".join(cols)]
    lines += [" | ".join(fmt(v) for v in r) for r in rows]
    return "\n".join(lines)


@tool
def run_readonly_query(sql: str) -> str:
    """Run ONE read-only DuckDB query (must start with SELECT or WITH) against
    data/marketing.duckdb and return the rows (max 200). Aggregate in SQL; follow the metric
    definitions exactly (NULLIF on every division, mature cohorts only, exclude Organic from
    paid metrics, aggregate ua_spend to cohort grain before joining cohorts).

    Args:
        sql: A single SELECT or WITH ... SELECT statement.
    """
    entry = {"query": sql.strip(), "rows": 0, "truncated": False, "error": None}
    TRACE.sql.append(entry)
    err = validate_select(sql)
    if err:
        entry["error"] = err
        return f"ERROR: {err}"
    con = _connect()
    timer = threading.Timer(config.SQL_TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(config.SQL_ROW_CAP + 1)
    except duckdb.Error as e:
        entry["error"] = str(e).splitlines()[0]
        return f"ERROR: {e}"
    finally:
        timer.cancel()
        con.close()
    truncated = len(rows) > config.SQL_ROW_CAP
    rows = rows[: config.SQL_ROW_CAP]
    entry.update(rows=len(rows), truncated=truncated)
    note = (f"\n(truncated to {config.SQL_ROW_CAP} rows: aggregate further)" if truncated
            else f"\n({len(rows)} rows)")
    return _format_rows(cols, rows) + note


@tool
def list_tables() -> str:
    """List the tables in data/marketing.duckdb with their columns, types, row counts and
    date ranges."""
    con = _connect()
    try:
        out = []
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables ORDER BY table_name").fetchall()]
        for t in tables:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position", [t]).fetchall()
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            date_col = next((c for c, ty in cols if ty == "DATE"), None)
            rng = ""
            if date_col:
                lo, hi = con.execute(f'SELECT MIN("{date_col}"), MAX("{date_col}") FROM "{t}"').fetchone()
                rng = f", {date_col} {lo} -> {hi}"
            out.append(f"{t} ({n:,} rows{rng})\n  " + ", ".join(f"{c} {ty}" for c, ty in cols))
        return "\n".join(out)
    finally:
        con.close()


@tool
def get_metric_definitions() -> str:
    """Return the authoritative metric definitions, table grains, join rules and house rules
    from CLAUDE.md. CLAUDE.md beats any wiki page or Slack message. Read this before writing
    SQL for CPI, CTR, IPM, ROAS, retention, ARPDAU or payer conversion."""
    text = config.CLAUDE_MD.read_text()
    start = text.find("## Dataset at a glance")
    return text[start:] if start >= 0 else text


ALL_TOOLS = [search_knowledge, list_tables, get_metric_definitions, run_readonly_query]
