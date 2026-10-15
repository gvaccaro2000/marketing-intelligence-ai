# Dice Kingdom — hidden anomalies (answer key)

> Spoiler file. Analysts should try to find these in `data/marketing.duckdb`
> before reading this file.

Data window: **2026-06-01 → 2026-08-29** (90 days), generated with `--seed 42`.
Figures below come from the default seed. Other seeds change the noise but not the patterns.

---

## 1. Creative fatigue: `TT-UGC-02` (TikTok, campaign `tiktok_spark_ugc`)

**What:** TikTok's best creative starts losing CTR on **2026-07-03**. CTR decays
exponentially (half-life about 2 weeks) to roughly 45% of its starting level. The
budget never moves off it. Its spend keeps growing with the channel, so it still takes
about 60% of the campaign budget.

| Period | CTR | CPI | Spend |
|---|---|---|---|
| Jun 01 – Jul 02 | 1.39% | $0.73 | $68k |
| Jul 03 – Aug 29 | 0.84% | $1.10 | $134k |

Daily snapshots: CTR 1.43% / CPI $0.69 (Jun 15) → 1.00% / $0.96 (Jul 16) →
0.64% / $1.45 (Aug 29). The sibling creatives `TT-UGC-01` and `TT-UGC-03` stay flat
at about 0.9–0.96% CTR. That rules out a channel-wide or seasonal cause.

**How to find it:** compute CTR and CPI by `creative_id` and week. Look for a creative
whose CTR trends down while its spend share stays high.

**Recommended action:** refresh the creative or start iterating on new concepts.
Cap `TT-UGC-02` spend or move budget to the other creatives. Watch CTR decay as a
leading indicator.

## 2. Channel CPI jump: AppLovin from 2026-07-17

**What:** AppLovin CPM steps up about 70% over three days starting **2026-07-17**
(day 47). CTR and CVR do not change. Daily spend stays flat, so the higher price
shows up directly as fewer installs.

| Period | CPI | CPM | CTR | Spend/day | Installs/day |
|---|---|---|---|---|---|
| Before Jul 17 | $1.23 | $8.45 | 1.81% | $10.9k | 8,885 |
| From Jul 17 | $1.88 | $12.93 | 1.81% | $11.3k | 6,012 |

That is about +53% CPI and about −32% installs for the same budget. AppLovin goes
from the cheapest major paid channel to the most expensive one. No other channel shifts
on that date.

**How to find it:** plot daily CPI by channel and look for a step change. Then break
CPI into CPM × (1 / CTR) × (1 / CVR). Only CPM moved, which points to an auction or
pricing change, not a creative or funnel problem.

**Recommended action:** review AppLovin bids and targets. Check whether a bid or
target change, an inventory change or competitor pressure explains it. Reallocate
budget until CPI recovers.

## 3. Country with great installs but terrible ROAS: Brazil (BR)

**What:** BR delivers by far the most installs at the lowest CPI. Its D1 retention is
only slightly below other markets. But almost nobody pays, so D7 ROAS is about 1/6
of every other country. The budget share for BR also **grows** over the period
(June 21.7% → July 24.9% → August 28.5% of spend), as if the team kept chasing cheap
installs.

Paid traffic only:

| Country | Spend | Installs | CPI | D1 ret | D7 payer % | D7 ROAS |
|---|---|---|---|---|---|---|
| US | $1.63M | 637k | $2.55 | 38.5% | 3.09% | 20.3% |
| **BR** | **$1.21M** | **2.33M** | **$0.52** | 34.7% | **0.20%** | **3.3%** |
| JP | $0.63M | 213k | $2.98 | 41.7% | 3.54% | 21.3% |
| DE | $0.45M | 202k | $2.23 | 39.2% | 2.86% | 18.8% |
| UK | $0.45M | 222k | $2.03 | 37.9% | 2.70% | 19.4% |
| FR | $0.45M | 242k | $1.86 | 37.5% | 2.50% | 18.3% |

BR is about half of all installs and about 25% of spend, but it returns only about
3 cents per dollar by D7, versus 18–21 cents elsewhere. The pattern holds on every
channel and on organic traffic too. So the problem is the market and its monetization,
not a single network. The payer rate is about 1/6 of normal, and ARPPU and ad
revenue per install are also depressed.

**How to find it:** join `cohorts` to `ua_spend` (aggregated to campaign × country ×
platform × day). Compute D7 ROAS and D7 payer conversion by country. Use only
matured cohorts, where `revenue_d7` is not NULL. Then compare that with installs and
CPI.

**Recommended action:** cut or cap BR spend. Switch BR to ROAS- or value-optimized
bidding. Test regional pricing or an ad-monetization-heavy setup before scaling again.

---

### Notes on data shape (not anomalies)
- Cohort metrics are NULL until they mature as of 2026-08-29: `d1_retained` for the
  last 1 day, `d7_retained` / `revenue_d7` / `payers_d7` for the last 7 days,
  `d30_retained` / `revenue_d30` for the last 30 days.
- `Organic` rows in `ua_spend` have zero spend, impressions and clicks. They only
  carry installs.
- Normal patterns: weekend uplift, a mild upward spend trend, iOS has higher CPI and
  higher monetization than Android, and JP has the best retention and payer rate.
