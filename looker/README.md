# LookML project: Dice Kingdom marketing

LookML for the three tables in `data/marketing.duckdb`, modelled as if they lived in Redshift
(schema `marketing`, connection `redshift_marketing`). Metric definitions follow `CLAUDE.md`.

```
looker/
  marketing.model.lkml               connection, includes, datagroup, 3 explores
  views/ua_spend.view.lkml           paid delivery, creative level: spend, impressions, clicks, installs, CPI, CTR, IPM
  views/spend_cohort_grain.view.lkml ua_spend summed to cohort grain (derived table, no creative_id)
  views/cohorts.view.lkml            retention D1/D7/D30, D7/D30 revenue, D7 payer conversion, D7/D30 ROAS
  views/daily_kpis.view.lkml         DAU, revenue, payers, ARPDAU, daily payer rate
  dashboards/weekly_ua.dashboard.lookml  KPI tiles, weekly spend trend, D7 ROAS by channel and country
  tests/                             parser + house-rule tests, LookML-to-SQL check against DuckDB
```

| Explore | Base | Use for |
|---|---|---|
| `ua_performance` | `cohorts` + `spend_cohort_grain` (one_to_one) | anything that combines spend with revenue or retention (ROAS, CPI by cohort) |
| `ua_spend` | `ua_spend` | delivery down to creative: CPI, CTR, IPM |
| `daily_kpis` | `daily_kpis` | game-wide DAU, ARPDAU, daily payer rate (no channel split possible) |

## Design choices

### 1. Fan-out: spend is summed to cohort grain before the join

`ua_spend` has one row per creative (3 per campaign); `cohorts` has no `creative_id`. Joining them
directly repeats each cohort row 3 times and triples installs, revenue and retention.
`spend_cohort_grain` is a derived table that sums `ua_spend` over
`install_date × channel × campaign × country × platform`, which matches `cohorts` row for row, so
the join in `ua_performance` is a true `one_to_one` on all five keys. Every view also has a primary
key, so Looker's symmetric aggregates would still protect sums if someone added a fanning join.
Organic rows are kept in the derived table (spend 0) so every cohort row finds its match and
installs reconcile (4,485,121 on both sides; checked in `tests/`). Cohort metrics cannot be split
by creative; use the `ua_spend` explore for creative-level delivery.

The derived table is persisted with the `marketing_daily` datagroup (rebuilds when
`MAX(date)` in `ua_spend` changes), `distribution_style: all` (about 12k rows) and sort key
`install_date`.

### 2. Maturity: immature cohorts are dropped from numerator AND denominator

Dn columns are NULL until a cohort is n days old (as of 2026-08-29: D1 ≤ 2026-08-28,
D7 ≤ 2026-08-22, D30 ≤ 2026-07-30). Plain `SUM(d7_retained) / SUM(installs)` would keep young
cohorts' installs in the denominator and understate retention; ROAS with all spend in the
denominator would understate ROAS the same way. So `cohorts` has a yes/no maturity flag per metric
column (`is_d7_mature` = `d7_retained IS NOT NULL`, `is_d7_revenue_mature` = `revenue_d7 IS NOT NULL`,
…), and each ratio's numerator and denominator are sum measures with the **same** filters:

- `roas_d7 = paid_revenue_d7 / spend_d7_mature`, both filtered `is_paid = yes` and
  `is_d7_revenue_mature = yes` (D30 the same with `revenue_d30`).
- `d7_retention = d7_retained / d7_mature_installs`, both filtered `is_d7_mature = yes`
  (D1, D30 and D7 payer conversion the same).

NULL is never treated as 0. On the dashboard, the latest week (2026-08-17 → 08-23) has D7 ROAS for
its mature days only (installs up to 2026-08-22). Revenue columns are cumulative, so they are
never added together.

### 3. Organic: excluded from every paid measure, by the measure itself

Organic has installs but no spend, impressions or clicks; left in, it would lower CPI and dilute
CTR/IPM. Every paid measure (spend, impressions, clicks, paid installs, CPI, CTR, IPM, ROAS and
its components) carries `filters: [is_paid: "yes"]`, so the exclusion holds whatever the user
filters. `installs` (all) and `organic_installs` exist separately for context. Retention, revenue
and payer conversion are not paid metrics and include Organic by default; split with `Is Paid`.

### Other conventions

- Every ratio is `sum(numerator) * 1.0 / NULLIF(sum(denominator), 0)` at the query grain (no
  averages of ratios; `* 1.0` avoids integer division on Redshift).
- Weeks run Monday to Sunday (`week_start_day: monday`), the same as the weekly UA report.
- `daily_kpis.dau` and `payers` summed over several days are user-days; labels say so, and they
  are meant for ARPDAU / daily payer rate. `daily_kpis` cannot be split by channel.
- The column `date` is quoted (`"date"`) in SQL.
- Every measure has a plain-English label and description (enforced by a test).

## Tests

```bash
pip install -r requirements.txt
python -m unittest discover -s looker/tests -v     # or: pytest looker/tests
python looker/tests/check_sql_logic.py --week 2026-08-10
```

- **Syntax:** every `.lkml` file parses with `lkml`; the dashboard parses as YAML and every field
  it uses exists in the `ua_performance` views.
- **House rules:** every measure has a label and description; every division uses `NULLIF`; paid
  measures filter out Organic in every `SUM`; Dn ratios use identical maturity filters on both sides;
  the join is `one_to_one` on all five cohort keys and the derived table has no `creative_id`.
- **SQL logic (DuckDB):** `tests/lookml_sql.py` renders the LookML measures to SQL the way Looker
  does (`${TABLE}`, `${field}`, filtered sums) and runs it against `data/marketing.duckdb` attached
  read-only as `marketing`. It checks the join adds no rows, installs and spend reconcile, and that
  CPI (from both `ua_spend` and `spend_cohort_grain`) and D7 ROAS by channel for the week
  2026-08-10 → 2026-08-16 equal the vetted weekly-report queries in `sql/weekly_ua/`:

| Channel | CPI | D7 ROAS |
|---|---|---|
| AppLovin | $1.3048 | 22.80% |
| Google | $1.5201 | 18.53% |
| Meta | $1.3801 | 19.12% |
| TikTok | $1.1101 | 22.22% |
| Unity | $0.7241 | 20.23% |

Installs/activity 2026-08-10 → 2026-08-16, all D7-mature (≤ 2026-08-22); paid channels only.
Match tolerance 1e-9.
