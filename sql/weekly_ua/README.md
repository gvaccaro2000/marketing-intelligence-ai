# Weekly UA report SQL

Vetted queries used by `scripts/weekly_ua_report.py` (skill: `.claude/skills/weekly-ua-report`).
All follow `CLAUDE.md`: `NULLIF` on every division, ratios from summed components,
Organic excluded from paid metrics, immature cohorts dropped from numerator and denominator.

Every query takes two named parameters (DuckDB `$name` syntax):

| Param | Meaning |
|---|---|
| `$week_start` | Monday of the report week (DATE). Current week = `week_start … week_start + 6`, previous week = the 7 days before. |
| `$as_of` | Data as-of date (`MAX(date)` in `ua_spend`). Used for cohort maturity. |

Breakdown queries use `GROUPING SETS` and return a `dim` column (`total`, `channel`, `country`)
so the script can check that breakdown rows sum to the total.

| File | Purpose |
|---|---|
| `paid_delivery.sql` | Spend, installs, impressions, clicks, CPI, CTR, IPM (paid, by activity date) |
| `paid_cohort_quality.sql` | D1/D7 retention, D7 payer conversion, ROAS D0/D7 (paid, mature cohorts only) |
| `organic_installs.sql` | Organic installs per week (context only) |
| `game_kpis.sql` | DAU, revenue, ARPDAU, daily payer rate from `daily_kpis` |
| `check_reconcile.sql` | `ua_spend` → cohort grain vs `cohorts`: rows, installs, spend through the join |
| `check_nulls.sql` | Unexpected NULLs / maturity violations / impossible values |
| `check_outliers.sql` | Channel-day spend, installs, CPI vs trailing-28-day baseline (robust z-score) |
