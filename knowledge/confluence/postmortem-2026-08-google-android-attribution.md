---
title: "Post-mortem: Google Android attribution outage (2026-08-06 → 2026-08-09)"
space: Analytics
owner: Kwame Asante
last_updated: 2026-08-17
status: final
severity: P1
---

# Post-mortem: Google Android attribution outage

## Summary

For four days (**2026-08-06 → 2026-08-09**, UTC) almost all Google Android installs were not
attributed to Google. Google kept delivering normally, but only ~6% of its Android installs
were credited to it. The rest were recorded as **Organic Android**. Google iOS and all other
networks were unaffected.

## Impact

| | Normal day (early Aug) | Outage days (avg) |
|---|---|---|
| Google Android spend | ~$5.8k | ~$6.2k |
| Google Android clicks | ~20.5k | ~22k |
| Google Android installs | ~4.5k | ~280 |
| Google Android CPI | ~$1.28 | ~$22 |
| Organic Android installs | ~4.1k | 8.2k – 9.3k |

- ~17k Google Android installs were counted as Organic. Total Android installs barely moved.
- Reported Google CPI and D7 ROAS for those days are wrong. Organic Android is inflated.
- **The data cannot be restated.** Attributa confirmed failed postbacks from the window can't
  be re-attributed, so the warehouse tables keep the misattribution permanently.

## Timeline (UTC)

| When | What |
|---|---|
| 2026-08-05 ~20:00 | Quarterly rotation of network API credentials |
| 2026-08-06 | First full day with ~6% of Google Android installs attributed |
| 2026-08-07 07:55 | Daniel flags Google Android CPI of $21 in #ua-team; asks whether to pause |
| 2026-08-07 08:45 | Kwame links the Organic Android spike to the Google drop (mirror image) |
| 2026-08-07 11:25 | Root cause found: Android Google link did not pick up new credentials. P1 opened with Attributa |
| 2026-08-07 11:30 | Decision: keep Google Android running, exclude the window from reads |
| 2026-08-09 late | Re-linked integration live |
| 2026-08-10 | Google Android back to ~4.5k installs, Organic Android back to ~4.1k |

## Root cause

The credential rotation script updated a shared secret store. The iOS link refreshed on its
next sync; the Android link held a cached token that expired, and the MMP silently fell back
to organic attribution instead of raising an error.

## What went well

- Nobody paused the campaigns. Spend and clicks were normal, which pointed at measurement.
- Checking Organic on the same platform found the cause within hours.

## What went badly

- No alert: we found it from a manual CPI check a day later.
- The rotation runbook didn't include per-link verification.

## Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Post-rotation health check for every network × platform link | Kwame Asante | Done |
| 2 | Alert: paid click→install CVR drop > 50% **and** same-platform Organic spike > 50% | Kwame Asante | Live 2026-08-17 |
| 3 | Annotate dashboards for 2026-08-06 → 08-09 | Ingrid Solberg | Done |
| 4 | Exclude Google Android 08-06 → 08-09 from CPI/ROAS trend reads and benchmarks | Ingrid Solberg | Done (report template) |
