---
title: D7 ROAS Definition (legacy, v1)
space: Analytics
owner: Ingrid Solberg
last_updated: 2026-05-18
status: deprecated
superseded_by: "Metric Definitions (v3)"
---

> ⚠️ **DEPRECATED — do not use.** This page is kept for history because older decks link to
> it. It was superseded on 2026-05-18 by **Metric Definitions (v3)**, which only counts mature
> cohorts and drops their spend too. Numbers computed with the formula below are **not
> comparable** with current reports.

# D7 ROAS Definition (v1)

*Original text, written 2025-11-04.*

D7 ROAS tells us how much of our spend comes back within a week.

## Formula

```sql
-- D7 ROAS for a reporting period
SUM(revenue_d7) / SUM(spend)
-- over all rows in the period
```

- Use all spend in the reporting period.
- Use the D7 revenue of all cohorts installed in the period. If a cohort has no D7 revenue yet,
  it simply contributes nothing.
- For a daily trend line, compute D7 ROAS per day and average the daily values over the week.

## Targets (2025)

- Blended D7 ROAS target: 15%.

## Known issues (added 2026-05-18)

- Treats missing (NULL) D7 revenue as 0 while keeping the spend: the latest 7 days always look
  bad.
- Averaging daily ROAS weights small days the same as big days.
- Both fixed in v3.
