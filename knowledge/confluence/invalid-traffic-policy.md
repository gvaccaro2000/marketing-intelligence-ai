---
title: Invalid Traffic Policy
space: User Acquisition
owner: Tomasz Wierzbicki
last_updated: 2026-07-18
status: current
---

# Invalid Traffic Policy

## Signs of click spam / install fraud

Look at the **combination**, not a single metric:

| Signal | Typical fraud pattern |
|---|---|
| CTR | Jumps several-fold with no creative change |
| Click→install CVR | Falls (lots of clicks, few real installs per click) |
| CPI | Falls sharply on flat spend ("too good to be true") |
| D1 retention | Falls sharply; fake installs don't come back |
| Cohort payer conversion D7 | Falls; fake installs don't pay |
| Revenue | Unchanged, so ROAS can look normal |
| CTIT (click-to-install time) | Long tail of very slow installs |

A campaign that gets "cheaper" overnight on all of its creatives at once is suspect until
proven otherwise.

## Process

1. Freeze budget (no scaling) as soon as the pattern is suspected.
2. Data check in #data-questions: CTR, CVR, CPI, D1, payer conversion by week vs the sister
   campaign on the same network.
3. Turn on stricter Attributa Protect rules for the campaign.
4. Open a ticket with the network; request sub-publisher / source-app breakdown and makegoods.
5. Blocklist offending sources.
6. Exclude the campaign from CPI benchmarks and install KPIs until clean.
7. If not clean within ~6 weeks, pause.

## Case log

| Campaign | Start | Status |
|---|---|---|
| `unity_video_retarget` | 2026-07-09 | Budget frozen 07-17; blocklist 07-24 (no effect); partial credit 08-25; pause from 09-01 |
