---
title: Weekly UA Report Template
space: User Acquisition
owner: Ingrid Solberg
last_updated: 2026-08-18
status: current
---

# Weekly UA Report Template

Posted every Monday in #ua-team and linked in #marketing-leads. Compare the last complete
Mon-Sun week with the previous Mon-Sun week. Never compare a day with the previous day
(weekend uplift).

## Header (required)

- **Activity window:** `YYYY-MM-DD → YYYY-MM-DD` (spend, installs, CPI)
- **D7 window:** latest 7 D7-mature install dates (lags the activity window by a week)
- **Data as-of date**
- **Known events in the window** (see *Known data events* below)

## Sections

1. **Headline** — 3 bullets max. Spend, installs, blended paid CPI, D7 ROAS. WoW %.
2. **By channel** — spend, installs, CPI, CTR, IPM, D7 ROAS. Paid only. Organic installs in a
   separate line, never inside CPI.
3. **By country** — same metrics.
4. **Cohort quality** — D1 / D7 retention by platform (Paid vs Organic split), cohort payer
   conversion D7. Say "cohort payer conversion D7" or "daily payer rate", never just
   "payer conversion".
5. **Actions** — what we changed, what we will change.

## Validation checklist (paste at the bottom)

- [ ] Channel rows sum to total spend and installs.
- [ ] `ua_spend` installs aggregated to cohort grain = `cohorts.installs` for the window.
- [ ] Join row count = cohort row count (no creative fan-out).
- [ ] Immature cohorts dropped from both numerator and denominator.

## Known data events (footnote when in window)

| Event | Window | Handling |
|---|---|---|
| unity_video_retarget invalid traffic | from 2026-07-09 | Footnote; exclude from CPI benchmarks and install KPIs |
| Android 2.14.0 retention drop | install cohorts from 2026-07-22 | Footnote Android retention/ROAS; not a UA issue |
| Google Android attribution outage | 2026-08-06 → 2026-08-09 | Exclude Google Android from CPI/ROAS trend; Organic Android inflated |
