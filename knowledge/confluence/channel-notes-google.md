---
title: Channel Notes — Google
space: User Acquisition
owner: Daniel Esposito
last_updated: 2026-08-15
status: current
---

# Channel Notes — Google

~24% of paid spend. Highest CPI of the five networks (~$1.57) and the lowest D7 ROAS, but
high CTR and good scale.

## Campaigns

| Campaign | Objective | Creatives |
|---|---|---|
| `uac_installs_global` | App campaign, install volume | GGL-UAC-01..03 |
| `uac_tcpa_payers` | App campaign, target CPA on first purchase | GGL-TCPA-01..03 |

## Notes

- **Never pause an app campaign to "fix" a reporting problem.** It resets learning and costs
  1-2 weeks of efficiency.
- tCPA changes: max 15% at a time, no more than twice a week.
- Attribution for Google runs through a separate link per platform in Attributa (our MMP).
  The Android and iOS links authenticate separately; a credential rotation must be checked on
  both.
- **2026-08-06 → 2026-08-09:** Google Android installs were under-attributed (only ~6% came
  through) because the Android link did not pick up rotated credentials. Delivery was normal.
  The missing installs were counted as Organic Android. Not restatable. Exclude these days
  from Google Android CPI/ROAS reads. See the post-mortem.
