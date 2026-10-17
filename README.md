# Marketing Intelligence practice project

Synthetic user-acquisition dataset for **Dice Kingdom**, a fictional free-to-play casual
mobile game. It covers 90 days (2026-06-01 → 2026-08-29), 6 channels (Meta, Google,
AppLovin, Unity, TikTok, Organic), 6 countries (US, UK, DE, JP, BR, FR) and 2 platforms.

## Generate the data

```bash
pip install -r requirements.txt
python scripts/generate_data.py          # writes data/marketing.duckdb and validates it
```

## Tables (`data/marketing.duckdb`)

| Table | Grain | Columns |
|---|---|---|
| `ua_spend` | date × channel × campaign × country × platform × creative | spend, impressions, clicks, installs |
| `cohorts` | install_date × channel × campaign × country × platform | installs, d1/d7/d30_retained, revenue_d0/d7/d30, payers_d7 |
| `daily_kpis` | date × platform | dau, revenue, payers |

Cohort metrics that have not matured by 2026-08-29 are NULL.

## Exercise

The data contains three hidden anomalies. Try to find them before you open
`answers/ANOMALIES.md`.

## Knowledge base

`knowledge/` holds a synthetic company knowledge base for the same period: Slack threads
(JSON) and Confluence-style wiki pages (Markdown). See `knowledge/README.md`.

## Analytics agent

`agent/` holds a LangChain agent (Claude plus tools) that answers questions using SQL on the
database and hybrid RAG over `knowledge/`, with citations. See `agent/README.md`.

## Slack bot (`/ask`)

`bot/ask_bot.py` exposes the analytics agent in Slack as a `/ask` slash command, using
`slack_bolt` in Socket Mode (no public URL needed).

**Slack app setup.** Enable Socket Mode, create an app-level token with `connections:write`,
add the `commands` bot scope, and create a `/ask` slash command. Install the app to the
workspace.

```bash
pip install -r requirements.txt -r agent/requirements.txt slack_bolt
export SLACK_BOT_TOKEN=xoxb-...      # Bot User OAuth token
export SLACK_APP_TOKEN=xapp-...      # app-level token (Socket Mode)
export DICE_AGENT_API_KEY=...        # Anthropic API key used by the agent
python bot/ask_bot.py
```

- If `agent/rag/index/` is missing, the bot runs `agent/rag/ingest.py` first.
- `/ask <question>` replies "Looking into it…" right away, within Slack's 3-second window.
  The agent then runs in a background thread, and the bot posts the question, the answer
  and a short list of sources to the channel. The source list holds the citations the
  answer used, plus a count of SQL queries. Replies are capped at 3,900 characters.
- `/ask` with no question replies with a usage example. Only the caller sees it.
- If the agent fails or takes longer than 90 s, the bot posts a short apology naming the
  error type. It never posts the error message, a stack trace or secrets.
- Questions run one at a time, because the agent's tool trace is shared by the whole
  process. A question waiting in the queue uses up part of its 90 s.
- Each question is logged to stdout with its duration, estimated cost and status. Tokens
  are never printed.

Tests: `python -m pytest tests/test_ask_bot.py`.
