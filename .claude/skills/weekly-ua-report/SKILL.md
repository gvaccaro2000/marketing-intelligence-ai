---
name: weekly-ua-report
description: Build the Dice Kingdom weekly user-acquisition (UA) report from data/marketing.duckdb and post it to Slack. Use when asked for the weekly UA report, a week-over-week (WoW) paid-media / channel / country update, or to post UA performance to Slack. Takes an optional week (any date in a Mon–Sun week); defaults to the last complete week in the data.
---

# Weekly UA report

Produces a validated, week-over-week UA summary for stakeholders (1 headline, 3 drivers,
1 recommended action, then a compact channel/country table) and posts it to Slack.

Everything numeric comes from vetted SQL in `sql/weekly_ua/` (see its README). Don't write
ad-hoc SQL for the report. If a number looks wrong, fix the vetted query and say so.
Follow `CLAUDE.md`: never read `scripts/generate_data.py` or `answers/`, and open the DB read-only.

## Inputs

- **Week** (optional): any `YYYY-MM-DD` inside the target week. Weeks run Monday–Sunday
  (2026-06-01 is a Monday). With no week given, the script picks the last complete week on or
  before the data as-of date (`MAX(date)` in `ua_spend`). The previous week must exist in the data.

## Steps

1. **Run the report** (no posting yet):

   ```bash
   python scripts/weekly_ua_report.py [--week YYYY-MM-DD]
   ```

   It writes `reports/weekly_ua_<monday>.{md,slack,json}` (git-ignored) and prints the Slack draft.
   Exit codes: `0` ok, `1` validation failed, `2` bad week (incomplete, or no previous week).

2. **Read the validation result.** The script checks, for both weeks:
   - `ua_spend` aggregated to cohort grain equals `cohorts.installs` row for row (FULL JOIN, so
     orphans on either side count), and paid spend is unchanged after the cohort join.
   - Channel rows and country rows each sum to the paid total (spend, installs, impressions,
     clicks), and delivery totals plus Organic installs equal cohort installs.
   - No NULLs where data should exist, no values for immature cohorts, no impossible values
     (negative spend, clicks > impressions, retained > installs, non-cumulative revenue, payers > DAU),
     and no missing days.
   - **Outliers** (warnings, not failures): channel-day and channel×country-day spend, installs
     and CPI with |robust z| ≥ 3.5 vs the trailing 28 days.

   If any check **fails**, stop. Don't post. Tell the user which check failed and the detail line.
   The script also refuses `--post` on failure. Use `--force-post` only if the user explicitly asks.

3. **Review the draft before posting.** Open the `.slack` file and the `.json` (`wow`, `drivers`,
   `outliers`). The narrative comes from rules:
   - **Headline:** paid spend, installs, blended CPI, D7 ROAS WoW, plus Organic installs.
   - **Drivers:** one per lens, each the largest USD-impact mover among channels and countries,
     with distinct entities: *Volume* (Δspend), *Efficiency* (ΔCPI × installs), *Quality*
     (ΔD7 ROAS × D7-mature spend).
   - **Action:** a channel more than 10% below blended D7 ROAS → trim ~10% of its spend; a channel
     more than 5% above blended, with ROAS not falling and CPI not up >5% → scale. Both → shift
     budget between them. Any failed check → hold. Outliers on the named channels add a "confirm
     with the MMP first" caveat.

   You may tighten the wording in the `.slack` file (e.g. if an outlier explains a driver, say so),
   but every number must come from the script output. Keep it short, keep the structure
   (headline → 3 drivers → 1 action → table → windows/validation footer), keep Slack mrkdwn
   (`*bold*`, `_italic_`, `•` bullets, table in a ``` block). No Markdown headings or `**`.

4. **Post** the reviewed file:

   ```bash
   python scripts/post_to_slack.py reports/weekly_ua_<monday>.slack
   ```

   (or run step 1 with `--post` when no edits are needed). The poster reads `$SLACK_WEBHOOK_URL`
   and **never prints it**. Never echo, log or paste the URL yourself either (no `echo $SLACK_WEBHOOK_URL`,
   no `env`/`printenv` dumps, no `curl` with the URL on the command line). Check the payload first
   with `--dry-run` if needed. Success prints `posted to Slack (N chars)`.

5. **Reply to the user** with the headline, the posted status, the validation result
   (`N/N checks passed`, outlier count) and the date windows (below).

## Date windows (state them in every report)

- Spend, installs, CPI, CTR, IPM: activity dates of the week vs the previous week (paid only).
- D1 retention: install dates of the week (all D1-mature for past weeks).
- D7 retention, D7 payer conversion, D7 ROAS: install dates of the week **through the last
  D7-mature day** (`as_of − 7`). For the latest week that is 6 of 7 days. Immature cohorts are dropped
  from numerator and denominator.
- Game KPIs (ARPDAU, daily payer rate, from `daily_kpis`): activity dates, all users. Full `.md` report only.

## Files

| Path | Role |
|---|---|
| `scripts/weekly_ua_report.py` | Runs SQL, validates, computes WoW, writes report + Slack draft, optional `--post` |
| `scripts/post_to_slack.py` | Posts a mrkdwn file to `$SLACK_WEBHOOK_URL` (`--dry-run` prints the payload) |
| `sql/weekly_ua/*.sql` | Vetted queries (`$week_start`, `$as_of` parameters) |
