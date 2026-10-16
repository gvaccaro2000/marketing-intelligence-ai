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
