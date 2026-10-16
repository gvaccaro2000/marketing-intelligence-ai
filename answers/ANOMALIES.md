# Dice Kingdom — hidden anomalies (answer key)

> Spoiler file. Analysts should try to find these in `data/marketing.duckdb`
> before reading this file.

Data window: **2026-06-01 → 2026-08-29** (90 days), generated with `--seed 20260916`.
Figures below come from the default seed. Other seeds change the noise but not the patterns.

---

## 1. Attribution outage: Google Android, 2026-08-06 → 2026-08-09

**What:** For four days, Google stops reporting almost all Android installs. Spend,
impressions and clicks stay normal, so the campaigns are still delivering. Only about
6% of installs are attributed. The missing installs show up as **Organic Android**
installs instead, which roughly double on exactly the same days. Google iOS is
unaffected.

| Google Android | Spend/day | Clicks/day | Installs/day | CPI |
|---|---|---|---|---|
| Jul 23 – Aug 23, excl. outage | ~$5.9k | ~21k | 4,582 | $1.29 |
| Aug 06 – Aug 09 (outage) | ~$6.2k | ~22k | **280** | **$22.16** |

Organic Android: about 4.1k installs/day before and after, **8.2k–9.3k/day** during the
outage (35,188 installs over the four days). Total Android installs barely move.

**How to find it:** plot daily installs and CPI by channel × platform. Google Android CPI
spikes about 17× for four days while clicks are flat, so click→install CVR collapses.
Put Organic installs for the same platform next to it. The mirror-image spike shows the
installs happened but lost attribution (SDK, postback or MMP issue), not that demand fell.

**Recommended action:** don't pause or cut Google on the basis of those four days. Raise
it with the MMP / Google measurement team, check SDK and postback health, and if
possible restate the affected days. Exclude the window from CPI and ROAS trend reads,
and add an alert on paid CVR drops alongside organic spikes.

## 2. Android retention regression from 2026-07-21 install cohorts

**What:** Every Android cohort installed on or after **2026-07-21** retains worse.
D1 drops about 18%, D7 about 32% and D30 about 38%. It hits every channel and
Organic alike. iOS cohorts are unchanged. CPI, CTR and installs do not move, so it
is not a traffic-quality problem. It points to a product change (an Android app
release) on that date. Android DAU in `daily_kpis` also falls faster than iOS
afterwards.

Android cohorts (excluding `unity_video_retarget`, see #3):

| Install cohorts | D1 | D7 | D30 |
|---|---|---|---|
| Before Jul 21 | 36.2% | 14.0% | 5.2% |
| From Jul 21 (mature only) | 29.9% | 9.7% | 3.4% |
| iOS before / after | 39.9% / 40.1% | 15.5% / 15.5% | 5.8% / 5.8% |

The drop is about the same within each channel (e.g. Meta Android D1 36.2% → 29.6%,
AppLovin 37.8% → 31.4%, Organic 41.5% → 34.0%).

**How to find it:** compute D1/D7 retention by `install_date` (or install week) ×
platform, mature cohorts only. A step change on one platform across all channels,
including Organic, rules out UA as the cause.

**Recommended action:** escalate to the product/engineering team. Check the Android
release history around 2026-07-20/21 (crashes, load time, tutorial or economy changes)
and consider a rollback or hotfix. Expect Android ROAS to soften as D7/D30 mature, and
don't blame the networks for it.

## 3. Invalid traffic (click spam): `unity_video_retarget` from 2026-07-09

**What:** From **2026-07-09** (ramping up over five days), the Unity campaign
`unity_video_retarget` starts getting a flood of fake installs on top of its real ones.
Spend per day is unchanged, but installs more than double, so CPI looks about 56%
cheaper. The extra installs come with a huge burst of clicks, so CTR roughly
quintuples and click→install CVR halves. The extra users almost never come back and
never pay. Blended D1 retention and payer conversion collapse. Revenue doesn't change,
so D7 ROAS stays flat: the campaign's apparent "efficiency" is fake.

| `unity_video_retarget` | Spend/day | Installs/day | CPI | CTR | CVR | D1 | D7 payer conv. |
|---|---|---|---|---|---|---|---|
| Jun 01 – Jul 08 | $2.56k | 2,228 | $1.15 | 1.60% | 34.2% | 34.3% | 1.73% |
| Jul 13 – Aug 29 (full ramp) | $2.77k | 5,482 | **$0.50** | **8.01%** | **15.7%** | **14.6%** | **0.76%** |

The sister campaign `unity_playable_installs` stays flat on every metric (CPI ~$1.16,
CTR 1.6%, D1 ~34%; the small D1 dip comes from #2).

**How to find it:** compare campaigns' CTR, CVR, CPI and D1 retention week by week.
A sudden jump in CTR with a fall in CVR and D1, on unchanged spend, is the classic
click-spam / install-fraud signature. Cohort-quality metrics (D1, payer conversion)
fall while ROAS stays flat because the fake installs add no revenue.

**Recommended action:** flag the campaign with Unity and the MMP's fraud tooling.
Ask for refunds or makegoods on the invalid installs, and check sub-publisher / source
app IDs to blocklist the offenders. Exclude the campaign's installs from install-volume
KPIs and CPI benchmarks until it's clean.

---

### Notes on data shape (not anomalies)
- Cohort metrics are NULL until they mature as of 2026-08-29: `d1_retained` for the
  last 1 day, `d7_retained` / `revenue_d7` / `payers_d7` for the last 7 days,
  `d30_retained` / `revenue_d30` for the last 30 days.
- `Organic` rows in `ua_spend` have zero spend, impressions and clicks. They only
  carry installs.
- Normal patterns: weekend uplift, a mild upward spend trend, iOS has higher CPI and
  higher monetization than Android, JP has the best retention and payer rate, and BR
  is a cheap, low-monetizing market (by design, with a stable budget share).
- Game-wide DAU slowly declines on both platforms because the legacy user base churns.
