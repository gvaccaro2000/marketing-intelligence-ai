"""Slack bot that exposes the Dice Kingdom analytics agent as a /ask slash command.

    export SLACK_BOT_TOKEN=xoxb-...  SLACK_APP_TOKEN=xapp-...  DICE_AGENT_API_KEY=...
    python bot/ask_bot.py

Runs in Socket Mode (no public URL needed). /ask is acknowledged within Slack's 3-second
window, the agent runs in a background worker, and the answer is posted to the channel with
respond(response_type="in_channel"). Tokens are read from the environment and never printed.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import config  # noqa: E402

BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
APP_TOKEN_ENV = "SLACK_APP_TOKEN"
TIMEOUT_S = 90
# Slack truncates message text above 40k chars, but long messages are unreadable; keep the
# whole reply well under the 4,000-char guideline for a single message.
MAX_MESSAGE_CHARS = 3900
MAX_SOURCES = 5

ACK_TEXT = "Looking into it…"
USAGE_TEXT = (
    "Ask me a question about Dice Kingdom UA performance, for example:\n"
    "`/ask Why did Android D1 retention drop in late July?`"
)

_CITATION_RE = re.compile(r"\[(?:Slack #[\w-]+ \d{4}-\d{2}-\d{2}|Confluence: [^\]]+)\]")


# ------------------------------------------------------------------ pure helpers (tested)

def parse_question(text: str | None) -> str | None:
    """Return the cleaned /ask question, or None when it is empty."""
    q = " ".join((text or "").split())
    return q or None


def to_mrkdwn(text: str) -> str:
    """Convert the agent's Markdown to Slack mrkdwn (bold and headings)."""
    text = re.sub(r"^#{1,6}\s+(.+?)\s*$", r"*\1*", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    return text


def pick_sources(answer: str, sources: list[dict], limit: int = MAX_SOURCES) -> list[str]:
    """Citations to list under the answer: the retrieved ones the answer cites, in answer
    order; if it cites none, the top retrieved hits. Never lists a citation that wasn't
    actually retrieved."""
    retrieved = list(dict.fromkeys(h["citation"] for s in sources for h in s.get("hits", [])))
    cited = [c for c in dict.fromkeys(_CITATION_RE.findall(answer)) if c in retrieved]
    return (cited or retrieved)[:limit]


def format_answer(question: str, answer: str, sources: list[dict], n_sql: int = 0,
                  limit: int = MAX_MESSAGE_CHARS) -> str:
    """The in-channel reply: question, answer, short source list; capped at `limit` chars."""
    head = f"*Q:* {question}\n\n"
    lines = [f"• {c}" for c in pick_sources(answer, sources)]
    if n_sql:
        lines.append(f"• [SQL] {n_sql} quer{'y' if n_sql == 1 else 'ies'} on marketing.duckdb")
    tail = "\n\n*Sources*\n" + "\n".join(lines) if lines else ""
    body = to_mrkdwn(answer.strip()) or "(no answer)"
    room = limit - len(head) - len(tail)
    if room < 200:                       # absurdly long question: trim it, keep the answer
        head = head[: max(0, limit - len(tail) - 220)] + "…*\n\n"
        room = limit - len(head) - len(tail)
    if len(body) > room:
        body = body[: room - len("\n…(truncated)")].rstrip() + "\n…(truncated)"
    return head + body + tail


def error_text(exc: BaseException) -> str:
    """Short apology naming the error type only: no message, stack trace or secrets."""
    kind = "Timeout" if isinstance(exc, (FutureTimeout, TimeoutError)) else type(exc).__name__
    detail = f" (no answer within {TIMEOUT_S}s)" if kind == "Timeout" else ""
    return f"Sorry, I couldn't answer that: {kind}{detail}. Please try again or rephrase."


# ------------------------------------------------------------------ agent runner

class AgentRunner:
    """Runs questions one at a time (the agent's tool TRACE is process-global, so concurrent
    runs would mix up SQL and sources) with a per-question timeout."""

    def __init__(self, ask, timeout_s: float = TIMEOUT_S) -> None:
        self._ask = ask
        self._timeout_s = timeout_s
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")

    def run(self, question: str):
        # A timed-out run can't be killed; it finishes in the background (the agent's own
        # tool-call and SQL limits bound it) and its result is discarded.
        return self._pool.submit(self._ask, question).result(timeout=self._timeout_s)


def handle_question(question: str, respond, runner: AgentRunner, log=print) -> None:
    """Run the agent and post the answer (or an apology) in the channel. Never raises."""
    t0 = time.monotonic()
    try:
        r = runner.run(question)
        text = format_answer(question, r.answer, r.sources, n_sql=len(r.sql))
        status, cost = "ok", r.cost_usd
    except BaseException as e:  # noqa: BLE001 - includes SystemExit from a missing API key
        text = error_text(e)
        status, cost = f"error={type(e).__name__}", 0.0
    log(f"[ask] question={question!r} duration={time.monotonic() - t0:.1f}s "
        f"cost=${cost:.4f} status={status}", flush=True)
    try:
        respond(text=text, response_type="in_channel")
    except Exception as e:  # noqa: BLE001
        log(f"[ask] failed to post reply: {type(e).__name__}", flush=True)


def register(app, runner: AgentRunner) -> None:
    @app.command("/ask")
    def ask_command(ack, command, respond):
        question = parse_question(command.get("text"))
        if question is None:
            ack(text=USAGE_TEXT)          # ephemeral, only the caller sees it
            return
        ack(text=ACK_TEXT)                # within Slack's 3 s window
        threading.Thread(target=handle_question, args=(question, respond, runner),
                         daemon=True).start()


# ------------------------------------------------------------------ startup

def ensure_index() -> None:
    if config.INDEX_DIR.exists():
        return
    print(f"RAG index missing at {config.INDEX_DIR}; building it (agent/rag/ingest.py)…", flush=True)
    subprocess.run([sys.executable, str(config.RAG_DIR / "ingest.py")], check=True)


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Set the {name} environment variable.")
    return v


def main() -> None:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    from agent.core import DiceAgent

    bot_token, app_token = _env(BOT_TOKEN_ENV), _env(APP_TOKEN_ENV)
    ensure_index()
    agent = DiceAgent()                   # fails fast if DICE_AGENT_API_KEY is missing
    app = App(token=bot_token)
    register(app, AgentRunner(agent.ask))
    print("Dice Kingdom /ask bot is running (Socket Mode). Ctrl+C to stop.", flush=True)
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
