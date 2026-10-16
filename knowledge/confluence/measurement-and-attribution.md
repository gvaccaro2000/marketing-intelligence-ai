---
title: Measurement & Attribution
space: Analytics
owner: Kwame Asante
last_updated: 2026-08-17
status: current
---

# Measurement & Attribution

## Stack

- **Attributa** is our MMP. It attributes installs to networks via one integration
  ("link") per network × platform, and sends postbacks back to the networks.
- **Attributa Protect** is its fraud module (click-flooding, CTIT, device-farm rules).
- Nightly pipeline loads three tables into the marketing warehouse: `ua_spend` (network
  spend/delivery joined to attributed installs, per creative), `cohorts` (per install cohort)
  and `daily_kpis` (game-wide, per platform). Everything is UTC.
- An install that no network claims is recorded as **Organic**.

## Things to know

- Organic is a residual. If a network link breaks, its installs land in Organic for the same
  platform. **An organic spike next to a paid install drop on the same platform = attribution
  problem, not demand change.**
- Spend, impressions and clicks come from the networks' APIs; installs come from Attributa.
  So delivery can look normal while installs vanish.
- Attributa cannot restate installs after failed postbacks.
- Protect rules only affect new installs; they don't rewrite warehouse history.
- `daily_kpis` can't be attributed to channels.

## Alerts

| Alert | Since |
|---|---|
| Paid click→install CVR drop > 50% + same-platform Organic spike > 50% | 2026-08-17 |
| Daily spend vs plan ± 25% per channel | 2025 |

## Runbooks

- Credential rotation: rotate → verify **each** network × platform link with a test install →
  check next-day attributed installs per link.
