---
title: Creative Testing Process
space: Creative
owner: Hana Kobayashi
last_updated: 2026-06-20
status: current
---

# Creative Testing Process

## Naming

`CHANNEL-CAMPAIGN-NN`, e.g. `META-AEO-01`, `GGL-TCPA-02`, `APL-ROAS-03`, `UNT-PLY-01`,
`TT-UGC-02`. Three live creatives per campaign. Organic has a single placeholder id `organic`.

## What we can measure per creative

`ua_spend` carries `creative_id`, so **CPI, CTR and IPM** can be read per creative.
`cohorts` has no creative dimension: **retention, payer conversion and ROAS cannot be split by
creative.** Creative decisions are therefore made on top-of-funnel metrics, with a
campaign-level quality check.

## Test cycle

1. New variant goes live next to the incumbent. Keep the incumbent live.
2. Run for **7 full days** (one full weekday/weekend cycle) or until each variant has
   ≥ 1M impressions, whichever is later.
3. Read IPM first, CTR second, CPI third. Differences under ~10% are noise.
4. Winner stays; loser is rotated out at the Tuesday rotation meeting.
5. Check campaign-level D1 retention didn't drop after the swap (creative can attract the
   wrong audience).

## Red flags

- **All creatives in a campaign move together** → it's not creative. Look at the network,
  traffic quality or measurement.
- CTR jumps a lot while installs per click falls → suspected click spam, see
  *Invalid Traffic Policy*.

## Fatigue

Refresh when CTR drops ≥ 20% from the creative's first two weeks.
