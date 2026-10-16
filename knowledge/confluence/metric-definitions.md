---
title: Metric Definitions (v3)
space: Analytics
owner: Ingrid Solberg
last_updated: 2026-08-18
status: current
supersedes: "D7 ROAS Definition (legacy, v1)"
---

# Metric Definitions (v3)

**This is the canonical definition page for marketing metrics.** If another page disagrees with
this one, this one wins. Source of truth: the marketing warehouse (`ua_spend`, `cohorts`,
`daily_kpis`). All dates are UTC.

## General rules

- Every ratio is **sum of numerator / sum of denominator** at the reporting grain. Never
  average per-row or per-day ratios.
- Every division uses `NULLIF(denominator, 0)`.
- `paid` means `channel <> 'Organic'`. CPI, CTR, IPM and ROAS are paid-only.
- Cohort metrics only use **mature** cohorts. A cohort is mature for day *n* when the value
  for day *n* is not NULL. Drop immature cohorts from numerator **and** denominator.
- `ua_spend` has a creative-level row; `cohorts` does not. Aggregate `ua_spend` to
  date × channel × campaign × country × platform before joining, or every cohort row is
  counted three times.

## Paid acquisition

| Metric | Definition |
|---|---|
| CPI | `SUM(spend) / NULLIF(SUM(installs), 0)` |
| CTR | `SUM(clicks) / NULLIF(SUM(impressions), 0)` |
| IPM | `SUM(installs) * 1000 / NULLIF(SUM(impressions), 0)` |
| Click→install CVR | `SUM(installs) / NULLIF(SUM(clicks), 0)` (diagnostic, used for fraud and attribution checks) |

## ROAS

ROAS Dn = cumulative revenue through day *n* of the cohorts ÷ spend that acquired **those same
cohorts**. Spend of immature cohorts is dropped too.

```sql
SUM(revenue_d7) FILTER (WHERE revenue_d7 IS NOT NULL)
  / NULLIF(SUM(spend) FILTER (WHERE revenue_d7 IS NOT NULL), 0)   AS roas_d7
```

Same pattern for D30 with `revenue_d30`. Revenue columns are cumulative: never add
`revenue_d0 + revenue_d7`.

> Changed in v3 (2026-05-18): the legacy definition divided the D7 revenue of the period by
> **all** spend in the period, including cohorts that had not reached day 7. That understated
> ROAS for recent weeks. See the deprecated page for history only.

## Retention

```sql
SUM(d7_retained) / NULLIF(SUM(installs) FILTER (WHERE d7_retained IS NOT NULL), 0)
```

Same for D1 and D30. Retention may include Organic; label it or split Paid vs Organic.

## Payer conversion

Two different metrics. **Always say which one you report.**

- **Cohort payer conversion D7** (default meaning of "payer conversion"): share of installers
  who paid within 7 days. `SUM(payers_d7) / NULLIF(SUM(installs) FILTER (WHERE payers_d7 IS NOT NULL), 0)`.
- **Daily payer rate**: paying users ÷ DAU, game-wide by platform, from `daily_kpis`.

## ARPDAU

`SUM(revenue) / NULLIF(SUM(dau), 0)` from `daily_kpis`. All users, paid and organic. Cannot
be split by channel.

## Maturity windows (data as of 2026-08-29)

| Metric | Last mature install date |
|---|---|
| D1 | 2026-08-28 |
| D7 (retention, revenue, payers) | 2026-08-22 |
| D30 | 2026-07-30 |

## Change log

- 2026-08-18: clarified the two payer-conversion metrics.
- 2026-06-10: added click→install CVR as a diagnostic.
- 2026-05-18: v3. Maturity-matched ROAS (replaces legacy D7 ROAS).
