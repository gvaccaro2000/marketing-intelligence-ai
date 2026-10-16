---
name: weekly-ua-report
description: Build the Dice Kingdom weekly user-acquisition (UA) report from data/marketing.duckdb and post it to Slack. Use when asked for the weekly UA report, a week-over-week (WoW) paid-media / channel / country update, or to post UA performance to Slack. Takes an optional week (any date in a Mon–Sun week); defaults to the last complete week in the data.
---

# Weekly UA report

Produces a validated UA summary for stakeholders and posts it to Slack: 1 headline, up to 3
**structural issues** (persistent problems that week-over-week deltas hide), 1 recommended action
chosen by dollar impact, and a one-line WoW recap. The Slack post must be readable by an exec in
30 seconds; detail tables live in the `.md` report.

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
   - The structural weekly series (`structural_weekly.sql`) covers consecutive full weeks, its
     channel and country rows sum to each weekly total, and its report and previous weeks tie out to
     the WoW queries (spend, installs, D7-mature revenue and spend).
   - **Outliers** (warnings, not failures): channel-day and channel×country-day spend, installs
     and CPI with |robust z| ≥ 3.5 vs the trailing 28 days.

   If any check **fails**, stop. Don't post. Tell the user which check failed and the detail line.
   The script also refuses `--post` on failure. Use `--force-post` only if the user explicitly asks.

3. **Review the draft before posting.** Open the `.slack` file and the `.json` (`structural`,
   `candidate_actions`, `wow`, `drivers`, `outliers`). The narrative comes from rules:
   - **Headline:** paid spend, installs, blended CPI, D7 ROAS WoW, plus Organic installs.
   - **Structural issues:** each channel and country over the report week + 7 trailing weeks,
     compared with the **rest of paid** (paid total minus itself, so a big entity doesn't dilute its
     own benchmark) and with its own history. Thresholds are constants at the top of the script.
     - *Persistent gap:* weekly D7 ROAS < 80% of rest of paid in each of the last ≥ 4 weeks.
       $ = (rest ROAS − ROAS) × weekly spend, last 4 weeks.
     - *Step change:* D7 ROAS down ≥ 15% after a split week vs before it (≥ 2 weeks each side,
       every week after below the earlier level). $ = (ROAS before − after) × weekly spend after.
     - *Budget drift:* spend share up ≥ 3pp (last 4 weeks vs before) while ROAS < rest of paid.
       $ = extra weekly spend × ROAS gap.
     - Context on each line: CPI vs rest of paid (when > 125% and ROAS isn't compensating), budget
       share, and D30 ROAS on D30-mature cohorts as a payback check. Issues under $1k/wk are dropped.
       Slack shows the top 3 by $; the `.md` has all, plus per-entity and weekly-index tables.
       Needs ≥ 6 weeks of history, else the section says so.
   - **Action:** one candidate per flagged entity (step → diagnose with partner/MMP, cut 25% if
     unexplained; persistent gap → move 25% of its spend to the rest of paid; drift → cap at the
     earlier share), plus the WoW rule below. Candidates are ranked by the **weekly D7 revenue at
     stake** in the problem they fix; Slack shows the top one, the `.md` lists all. $ assume average
     returns on redeployed budget, so they are directional. Any failed check → hold.
     The `.json` `preset` field holds the recommended action as `{mode, moves, rebalance}` for the
     budget simulator (step 7); `null` on hold.
   - **WoW rule** (one candidate): channel > 10% below blended D7 ROAS → trim 10%; channel > 5%
     above, ROAS not falling, CPI not up > 5% → scale; both → shift. Outliers on the action's
     channel add a "confirm with the MMP" caveat.
   - **WoW recap:** one line with the largest USD mover per lens (distinct entities): *Volume*
     (Δspend), *Efficiency* (ΔCPI × installs), *Quality* (ΔD7 ROAS × D7-mature spend).

   You may tighten the wording in the `.slack` file, but every number must come from the script
   output. Keep it short (≈1,300 chars; exec-readable in 30 seconds) and keep the structure
   (headline → structural issues → 1 action → WoW line → windows/validation footer). Use Slack mrkdwn
   (`*bold*`, `_italic_`, `•` bullets). No Markdown headings, no `**`, no tables in Slack.

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

6. **Export dashboard data** (final step, every run):

   ```bash
   python scripts/export_dashboard_data.py
   ```

   It writes CSVs to `reports/dashboard/` (git-ignored) from `sql/weekly_ua/dashboard_weekly.sql`.
   It always covers **every complete Mon–Sun week** in the data, and the latest complete week, even
   if step 1 used `--week` for an earlier one.

   | File | Columns |
   |---|---|
   | `weekly_total.csv` | `week_start, spend, installs, cpi, d7_revenue, d7_mature_spend, roas_d7, organic_installs` |
   | `weekly_channel.csv` | `week_start, channel` + the same metrics, paid channels only (no `organic_installs`) |
   | `weekly_country.csv` | `week_start, country` + the same metrics, incl. that country's `organic_installs` |
   | `latest_channel.csv` | `channel, spend, installs, cpi, roas_d7, spend_share, spend_wow, cpi_wow, roas_d7_wow_pp` |
   | `latest_country.csv` | the same by `country` |

   - Spend, installs, CPI: paid only (`channel <> 'Organic'`), activity dates of the week.
   - `d7_revenue`, `d7_mature_spend`, `roas_d7`: D7-mature cohorts only (install date ≤ `as_of − 7`),
     in numerator and denominator. In the latest week that's 6 of 7 install days, so
     `d7_mature_spend` < `spend` there.
   - `spend_share` = share of the week's paid spend; `spend_wow`, `cpi_wow` = change vs the previous
     week as fractions (0.05 = +5%); `roas_d7_wow_pp` = change in D7 ROAS in percentage points.
   - Before writing it checks: complete consecutive weeks, `ua_spend` → cohort grain equals
     `cohorts.installs` row for row, the cohort join keeps paid spend and installs (no fan-out),
     channel and country rows sum to each weekly total, and D7 maturity. It prints `N/N passed`.
     **Exit 1 = a check failed and nothing was written.** Tell the user which check failed.
     Add the export's check result to your reply.

7. **Build the budget simulator** (after step 6):

   ```bash
   python scripts/build_simulator.py
   ```

   It fills the `DATA` and `PRESET` blocks of the template `artifacts/budget_simulator.html` and
   writes `reports/budget_simulator.html` (git-ignored).
   - `DATA` (baseline): average of the **last 4 complete weeks** per channel and per country from
     `reports/dashboard/weekly_{channel,country}.csv`: weekly spend, weekly installs, and D7 ROAS =
     Σ D7 revenue / Σ D7-mature spend over those weeks. The page's window label is updated too.
   - `PRESET`: the `preset` field of `reports/weekly_ua_<latest week>.json`, the recommended action
     in machine-readable form (`mode` channel/country, `moves` USD/wk per line, `rebalance` = spread
     freed budget over the other lines). If the report holds budgets (failed check or no candidate),
     `preset` is `null` and the page's "Apply this week's recommendation" button is disabled.
   - Checks before writing: 4 consecutive complete weeks, every line present in each week, lines
     sum to the weekly totals, the report is for the latest exported week (so step 1 must run without
     `--week`, or pass `--report`), and preset lines exist in the baseline. **Exit 1 = a check failed
     and nothing was written; exit 2 = an input file is missing** (run steps 1 and 6 first).
   - Edit the page layout in the template, not in `reports/`, and keep its `BEGIN/END` markers.

## Date windows (state them in every report)

- Spend, installs, CPI, CTR, IPM: activity dates of the week vs the previous week (paid only).
- D1 retention: install dates of the week (all D1-mature for past weeks).
- D7 retention, D7 payer conversion, D7 ROAS: install dates of the week **through the last
  D7-mature day** (`as_of − 7`). For the latest week that is 6 of 7 days. Immature cohorts are dropped
  from numerator and denominator.
- Game KPIs (ARPDAU, daily payer rate, from `daily_kpis`): activity dates, all users. Full `.md` report only.
- Structural issues: install weeks `week_start − 7w` → last D7-mature day (8 weeks); "now" = last 4
  weeks. D30 payback check: same start → `as_of − 30`, D30-mature cohorts only.

## Files

| Path | Role |
|---|---|
| `scripts/weekly_ua_report.py` | Runs SQL, validates, computes WoW, writes report + Slack draft, optional `--post` |
| `scripts/export_dashboard_data.py` | Validates and writes weekly dashboard CSVs to `reports/dashboard/` (step 6) |
| `scripts/build_simulator.py` | Fills the budget simulator template with the 4-week baseline and the report's preset (step 7) |
| `artifacts/budget_simulator.html` | Budget simulator template (`DATA` / `PRESET` blocks between `BEGIN/END` markers) |
| `scripts/post_to_slack.py` | Posts a mrkdwn file to `$SLACK_WEBHOOK_URL` (`--dry-run` prints the payload) |
| `sql/weekly_ua/*.sql` | Vetted queries (`$week_start`, `$as_of` parameters) |
