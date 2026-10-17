"""Tests for bot/ask_bot.py: parsing, formatting and error handling (no Slack or API calls)."""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import ask_bot  # noqa: E402
from bot.ask_bot import (  # noqa: E402
    ACK_TEXT, USAGE_TEXT, AgentRunner, error_text, format_answer, handle_question,
    parse_question, pick_sources, register,
)

SOURCES = [
    {"query": "q", "hits": [
        {"citation": "[Slack #ua-team 2026-07-14]"},
        {"citation": "[Confluence: Q3 Post-mortem]"},
        {"citation": "[Slack #ua-team 2026-07-14]"},
    ]},
    {"query": "q2", "hits": [{"citation": "[Confluence: Metric Definitions v3]"}]},
]


def result(answer="Because of click spam [Confluence: Q3 Post-mortem].", sources=SOURCES, sql=1):
    return SimpleNamespace(answer=answer, sources=sources, sql=[{}] * sql, cost_usd=0.0213)


class Recorder:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, **kw):
        if self.fail:
            raise RuntimeError("network")
        self.calls.append(kw)


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("text", [None, "", "   ", "\n\t "])
def test_parse_question_empty(text):
    assert parse_question(text) is None


def test_parse_question_normalises_whitespace():
    assert parse_question("  why did\n CPI   drop? ") == "why did CPI drop?"


# ------------------------------------------------------------------ formatting

def test_pick_sources_prefers_cited_and_dedupes():
    assert pick_sources("x [Confluence: Q3 Post-mortem] y [Confluence: Q3 Post-mortem]", SOURCES) == [
        "[Confluence: Q3 Post-mortem]"]


def test_pick_sources_ignores_invented_citation_and_falls_back():
    got = pick_sources("see [Confluence: Made Up Page]", SOURCES)
    assert got == ["[Slack #ua-team 2026-07-14]", "[Confluence: Q3 Post-mortem]",
                   "[Confluence: Metric Definitions v3]"]


def test_pick_sources_limit():
    many = [{"hits": [{"citation": f"[Confluence: P{i}]"} for i in range(10)]}]
    assert len(pick_sources("", many)) == ask_bot.MAX_SOURCES


def test_format_answer_contains_question_answer_sources():
    text = format_answer("Why?", "**Click spam** on Unity [Confluence: Q3 Post-mortem].", SOURCES, n_sql=2)
    assert text.startswith("*Q:* Why?")
    assert "*Click spam* on Unity" in text              # Markdown bold -> mrkdwn
    assert "• [Confluence: Q3 Post-mortem]" in text
    assert "• [SQL] 2 queries" in text


def test_format_answer_headings_to_bold():
    assert "*Summary*" in format_answer("q", "## Summary\nok", [])


def test_format_answer_no_sources_section_when_none():
    assert "Sources" not in format_answer("q", "ok", [], n_sql=0)


@pytest.mark.parametrize("qlen,alen", [(10, 20_000), (10_000, 10_000), (3_000, 3_000)])
def test_format_answer_respects_limit(qlen, alen):
    text = format_answer("q" * qlen, "a" * alen, SOURCES, n_sql=1)
    assert len(text) <= ask_bot.MAX_MESSAGE_CHARS
    assert "*Sources*" in text


# ------------------------------------------------------------------ error handling

def test_error_text_names_type_only():
    msg = error_text(ValueError("api_key=sk-ant-secret Traceback (most recent call last)"))
    assert "ValueError" in msg and "secret" not in msg and "Traceback" not in msg


def test_timeout_runner_and_message():
    runner = AgentRunner(lambda q: time.sleep(1), timeout_s=0.05)
    respond, logs = Recorder(), []
    handle_question("slow?", respond, runner, log=lambda *a, **k: logs.append(a[0]))
    assert "Timeout" in respond.calls[0]["text"] and "90s" in respond.calls[0]["text"]
    assert respond.calls[0]["response_type"] == "in_channel"
    assert "status=error=TimeoutError" in logs[0]


def test_agent_exception_is_caught_without_secrets():
    def boom(q):
        raise RuntimeError("Bearer xoxb-123-secret")
    respond, logs = Recorder(), []
    handle_question("q", respond, AgentRunner(boom), log=lambda *a, **k: logs.append(a[0]))
    text = respond.calls[0]["text"]
    assert "RuntimeError" in text and "xoxb" not in text
    assert "xoxb" not in logs[0]


def test_system_exit_from_agent_is_caught():
    def no_key(q):
        raise SystemExit("Set the DICE_AGENT_API_KEY environment variable")
    respond = Recorder()
    handle_question("q", respond, AgentRunner(no_key), log=lambda *a, **k: None)
    assert "SystemExit" in respond.calls[0]["text"]


def test_success_posts_in_channel_and_logs_cost():
    respond, logs = Recorder(), []
    handle_question("Why?", respond, AgentRunner(lambda q: result()),
                    log=lambda *a, **k: logs.append(a[0]))
    call = respond.calls[0]
    assert call["response_type"] == "in_channel"
    assert "*Q:* Why?" in call["text"] and "• [Confluence: Q3 Post-mortem]" in call["text"]
    assert "question='Why?'" in logs[0] and "cost=$0.0213" in logs[0] and "duration=" in logs[0]


def test_respond_failure_does_not_raise():
    logs = []
    handle_question("q", Recorder(fail=True), AgentRunner(lambda q: result()),
                    log=lambda *a, **k: logs.append(a[0]))
    assert "failed to post reply: RuntimeError" in logs[-1]


# ------------------------------------------------------------------ slash command wiring

class FakeApp:
    def command(self, name):
        def deco(fn):
            self.name, self.fn = name, fn
            return fn
        return deco


def test_command_empty_question_replies_usage_without_running_agent():
    app, acks, ran = FakeApp(), [], []
    register(app, AgentRunner(lambda q: ran.append(q)))
    app.fn(ack=lambda **kw: acks.append(kw), command={"text": "  "}, respond=Recorder())
    assert app.name == "/ask" and acks == [{"text": USAGE_TEXT}] and ran == []


def test_command_acks_then_answers_in_background():
    app, acks, respond = FakeApp(), [], Recorder()
    register(app, AgentRunner(lambda q: result()))
    app.fn(ack=lambda **kw: acks.append(kw), command={"text": "why?"}, respond=respond)
    assert acks == [{"text": ACK_TEXT}]
    for _ in range(100):
        if respond.calls:
            break
        time.sleep(0.02)
    assert respond.calls and "*Q:* why?" in respond.calls[0]["text"]
