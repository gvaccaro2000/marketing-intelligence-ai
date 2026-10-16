"""The Dice Kingdom analytics agent: Claude (langchain-anthropic) + SQL tools + knowledge search."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from pydantic import SecretStr

from agent import config
from agent.tools import ALL_TOOLS, TRACE

SYSTEM_PROMPT = f"""You are the analytics assistant for the growth team behind Dice Kingdom, a
free-to-play mobile game. You answer questions about user acquisition (UA) performance using
two kinds of evidence:

1. The database data/marketing.duckdb (tables ua_spend, cohorts, daily_kpis; data 2026-06-01 →
   2026-08-29, as-of date 2026-08-29). Use run_readonly_query for EVERY number you report.
   Call get_metric_definitions before writing metric SQL and follow it exactly.
2. The internal knowledge base (Slack threads, Confluence pages). Use search_knowledge for
   context, explanations, incidents, and decisions ("why", "what did we decide", "who").

Rules:
- Numbers come from SQL, never from documents. Slack/Confluence figures are what people saw at
  the time; if you quote one, say it is quoted and check it against the database when you can.
- CLAUDE.md (returned by get_metric_definitions) beats any document. If a wiki page or Slack
  message defines a metric differently, follow CLAUDE.md and say the page disagrees.
- Never use a page marked DEPRECATED (or superseded) for definitions or numbers. Prefer
  current/final pages over drafts and over older pages on the same topic; check status and
  dates. People in Slack sometimes guess wrong: read threads to the end and prefer the later,
  corrected conclusion.
- Cite every source inline, right after the claim it supports, exactly as given in the search
  results: [Slack #channel YYYY-MM-DD] or [Confluence: title]. Copy the citation string
  verbatim; for a Slack thread always use the thread's citation (its start date), even when
  quoting a later reply. Mark database numbers [SQL].
- When sources conflict with each other or with the data, say so explicitly and say which one
  you trust and why.
- Never guess. If the data cannot answer (e.g. cohorts are not mature yet, the date is outside
  the data, the information is not in any source), say so plainly and explain why, instead of
  estimating. Do not invent numbers, people, or decisions.
- State the date range (activity or install dates, and maturity windows) for every metric.
- Budget: at most {config.MAX_TOOL_CALLS} tool calls per question. Plan: combine metrics in
  one query, and issue independent tool calls in parallel. Return aggregated results, not raw rows.

Answer format: a direct answer first (1-3 sentences), then the supporting evidence as short
bullets with citations. Keep it concise."""


@dataclass
class AgentResult:
    question: str
    answer: str
    sql: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    tool_calls: int = 0
    usage: dict = field(default_factory=dict)

    @property
    def retrieved_paths(self) -> list[str]:
        return list(dict.fromkeys(h["path"] for s in self.sources for h in s["hits"]))

    @property
    def cost_usd(self) -> float:
        # claude-sonnet-5-5 list prices per 1M tokens: $2 input, $10 output,
        # cache writes 1.25x input, cache reads $0.20.
        u = self.usage
        return (
            u.get("input", 0) * 2.0 + u.get("cache_write", 0) * 2.5
            + u.get("cache_read", 0) * 0.2 + u.get("output", 0) * 10.0
        ) / 1e6


def _api_key() -> SecretStr:
    key = os.environ.get(config.API_KEY_ENV)
    if not key:
        raise SystemExit(f"Set the {config.API_KEY_ENV} environment variable (Anthropic API key).")
    return SecretStr(key)


def build_agent():
    from langchain.agents import create_agent
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
    from langchain_anthropic import ChatAnthropic
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    model = ChatAnthropic(
        model=config.MODEL,
        api_key=_api_key(),            # passed explicitly; SecretStr keeps it out of reprs/logs
        max_tokens=config.MAX_OUTPUT_TOKENS,
        output_config={"effort": "medium"},
        max_retries=3,
    )
    return create_agent(
        model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # Hard cap on tool executions; extra calls are blocked with an error message so
            # the model must answer with what it has.
            ToolCallLimitMiddleware(run_limit=config.MAX_TOOL_CALLS, exit_behavior="continue"),
            # Backstop on model round-trips (8 tool rounds + final answer + slack).
            ModelCallLimitMiddleware(run_limit=config.MAX_TOOL_CALLS + 2, exit_behavior="end"),
            # Cache tools + system prompt + growing conversation between round-trips.
            AnthropicPromptCachingMiddleware(ttl="5m"),
        ],
    )


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


class DiceAgent:
    def __init__(self) -> None:
        self.graph = build_agent()

    def ask(self, question: str) -> AgentResult:
        from langchain_core.messages import AIMessage

        TRACE.reset()
        state = self.graph.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"recursion_limit": 4 * config.MAX_TOOL_CALLS + 10},
        )
        msgs = state["messages"]
        ai = [m for m in msgs if isinstance(m, AIMessage)]
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for m in ai:
            u = m.usage_metadata or {}
            d = u.get("input_token_details", {}) or {}
            cr, cw = d.get("cache_read", 0) or 0, d.get("cache_creation", 0) or 0
            usage["input"] += u.get("input_tokens", 0) - cr - cw
            usage["output"] += u.get("output_tokens", 0)
            usage["cache_read"] += cr
            usage["cache_write"] += cw
        answer = next((_text(m.content) for m in reversed(ai) if _text(m.content).strip()), "")
        if not answer:
            answer = "(No answer: the tool-call budget ran out before the agent could answer.)"
        return AgentResult(
            question=question,
            answer=answer.strip(),
            sql=[dict(s) for s in TRACE.sql],
            sources=[dict(s) for s in TRACE.sources],
            tool_calls=sum(len(m.tool_calls) for m in ai),
            usage=usage,
        )
