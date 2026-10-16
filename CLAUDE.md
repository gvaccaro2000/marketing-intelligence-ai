# CLAUDE.md — Dice Kingdom marketing analytics

Guidance for analysis work on `data/marketing.duckdb`: synthetic user-acquisition (UA) data for
**Dice Kingdom**, a fictional free-to-play casual mobile game.

## Hard rules (read first)

- **Never read `scripts/generate_data.py` or anything in `answers/` during an analysis task.**
  Both reveal how the data was built and where the planted anomalies are. Work only from the
  database. (Running the generator to rebuild the DB is fine. Reading its source is not.)
- Open the database read-only: `duckdb.connect('data/marketing.duckdb', read_only=True)`.

## Dataset at a glance

| Dimension | Values |
|---|---|
| Date range | `2026-06-01` → `2026-08-29` (90 days, every table) |
| Data as-of date | `2026-08-29` (cohort maturity is measured against this date) |
| Channels | `Meta`, `Google`, `AppLovin`, `Unity`, `TikTok`, `Organic` |
| Countries | `US`, `UK`, `DE`, `JP`, `BR`, `FR` |
| Platforms | `iOS`, `Android` |

Campaigns (2 per paid channel, 3 creatives each; Organic has one pseudo-campaign/creative):

| Channel | Campaigns | Creative IDs |
|---|---|---|
| Meta | `meta_aeo_purchase_t1`, `meta_broad_installs` | `META-AEO-0[1-3]`, `META-BRD-0[1-3]` |
| Google | `uac_installs_global`, `uac_tcpa_payers` | `GGL-UAC-0[1-3]`, `GGL-TCPA-0[1-3]` |
| AppLovin | `applovin_cpi_scale`, `applovin_roas_d7` | `APL-CPI-0[1-3]`, `APL-ROAS-0[1-3]` |
| Unity | `unity_playable_installs`, `unity_video_retarget` | `UNT-PLY-0[1-3]`, `UNT-VID-0[1-3]` |
| TikTok | `tiktok_spark_ugc`, `tiktok_value_bidding` | `TT-UGC-0[1-3]`, `TT-VAL-0[1-3]` |
| Organic | `organic` | `organic` |

## Table schemas and grain

### `ua_spend` — paid-media delivery (33,480 rows)

**Grain:** one row per `date × channel × campaign × country × platform × creative_id` (verified unique).

| Column | Type | Notes |
|---|---|---|
| `date` | DATE | Delivery date |
| `channel` | VARCHAR | |
| `campaign` | VARCHAR | |
| `country` | VARCHAR | |
| `platform` | VARCHAR | |
| `creative_id` | VARCHAR | Only table with creative-level detail |
| `spend` | DECIMAL(12,2) | USD. Always `0` for Organic |
| `impressions` | BIGINT | Always `0` for Organic |
| `clicks` | BIGINT | Always `0` for Organic |
| `installs` | BIGINT | Attributed installs (Organic installs are recorded here too) |

No NULLs in any column.

### `cohorts` — install cohorts with retention and revenue (11,880 rows)

**Grain:** one row per `install_date × channel × campaign × country × platform` (verified unique).
No `creative_id`, so cohort metrics can't be split by creative.

| Column | Type | Notes |
|---|---|---|
| `install_date` | DATE | Cohort date |
| `channel`, `campaign`, `country`, `platform` | VARCHAR | Same values as `ua_spend` |
| `installs` | BIGINT | Cohort size |
| `d1_retained` | BIGINT | Users active on day 1. NULL when `install_date > 2026-08-28` |
| `d7_retained` | BIGINT | Users active on day 7. NULL when `install_date > 2026-08-22` |
| `d30_retained` | BIGINT | Users active on day 30. NULL when `install_date > 2026-07-30` |
| `revenue_d0` | DECIMAL(12,2) | Cumulative revenue on install day. Never NULL |
| `revenue_d7` | DECIMAL(12,2) | Cumulative revenue through day 7. NULL when immature (same as D7) |
| `revenue_d30` | DECIMAL(12,2) | Cumulative revenue through day 30. NULL when immature (same as D30) |
| `payers_d7` | BIGINT | Users who paid by day 7. NULL when immature (same as D7) |

NULL counts: D1 = 132 rows (1 day), D7 = 924 rows (7 days), D30 = 3,960 rows (30 days).
Revenue columns are cumulative (`revenue_d0 ≤ revenue_d7 ≤ revenue_d30`). Don't add them together.

**Reconciliation:** `SUM(ua_spend.installs)` grouped to cohort grain equals `cohorts.installs`
row-for-row (11,880/11,880 match; total 4,485,121 installs).

### `daily_kpis` — game-wide daily KPIs (180 rows)

**Grain:** one row per `date × platform` (verified unique). No channel, campaign or country.

| Column | Type | Notes |
|---|---|---|
| `date` | DATE | |
| `platform` | VARCHAR | |
| `dau` | BIGINT | Daily active users (all sources, including Organic) |
| `revenue` | DECIMAL(12,2) | Total revenue that day (USD) |
| `payers` | BIGINT | Distinct paying users that day |

`dau` and `payers` are daily distinct counts. Summing them over several days counts
**user-days**, not unique users. Only use the sums as denominators/numerators in ratios.

### Joining tables

- `ua_spend` → `cohorts`: **aggregate `ua_spend` to cohort grain first** (drop `creative_id`),
  then join on `date = install_date` and `channel, campaign, country, platform`. Joining
  without aggregating first duplicates each cohort row 3× (once per creative).
- `daily_kpis` only joins on `date` and `platform`. It can't be attributed to channels.

## Metric definitions (exact SQL)

General conventions:
- Every division uses `NULLIF(denominator, 0)`.
- Always compute ratios as **sum of numerator / sum of denominator** at the reporting grain.
  Never average per-row ratios.
- Multiply by `1.0` (or cast to `DOUBLE`) so integer and DECIMAL division doesn't truncate.
- `paid` means `channel <> 'Organic'`.

### Paid acquisition metrics (source: `ua_spend`; always exclude Organic)

```sql
-- CPI: cost per install (USD)
SUM(spend) * 1.0 / NULLIF(SUM(installs), 0)                   AS cpi

-- CTR: click-through rate
SUM(clicks) * 1.0 / NULLIF(SUM(impressions), 0)               AS ctr

-- IPM: installs per mille (installs per 1,000 impressions)
SUM(installs) * 1000.0 / NULLIF(SUM(impressions), 0)          AS ipm
-- ... FROM ua_spend WHERE channel <> 'Organic'
```

### ROAS (source: `cohorts` + `ua_spend` aggregated to cohort grain; exclude Organic)

ROAS Dn = cumulative cohort revenue through day n ÷ spend that acquired **the same mature
cohorts**. Spend for immature cohorts must be dropped as well, not only their revenue.

```sql
WITH spend AS (
  SELECT date AS install_date, channel, campaign, country, platform,
         SUM(spend) AS spend
  FROM ua_spend
  WHERE channel <> 'Organic'
  GROUP BY ALL
),
c AS (
  SELECT c.*, s.spend
  FROM cohorts c
  JOIN spend s USING (install_date, channel, campaign, country, platform)
  WHERE c.channel <> 'Organic'
)
SELECT
  -- ROAS D7: only cohorts with matured D7 revenue
  SUM(revenue_d7)  FILTER (WHERE revenue_d7  IS NOT NULL) * 1.0
    / NULLIF(SUM(spend) FILTER (WHERE revenue_d7  IS NOT NULL), 0)  AS roas_d7,
  -- ROAS D30: only cohorts with matured D30 revenue
  SUM(revenue_d30) FILTER (WHERE revenue_d30 IS NOT NULL) * 1.0
    / NULLIF(SUM(spend) FILTER (WHERE revenue_d30 IS NOT NULL), 0)  AS roas_d30
FROM c;
```

### Retention (source: `cohorts`)

Retention Dn = users retained on day n ÷ installs of **mature cohorts only**. Plain
`SUM(d7_retained) / SUM(installs)` is wrong: SUM skips NULL numerators but keeps their
installs in the denominator, which pushes retention down.

```sql
SUM(d1_retained)  * 1.0 / NULLIF(SUM(installs) FILTER (WHERE d1_retained  IS NOT NULL), 0) AS d1_retention,
SUM(d7_retained)  * 1.0 / NULLIF(SUM(installs) FILTER (WHERE d7_retained  IS NOT NULL), 0) AS d7_retention,
SUM(d30_retained) * 1.0 / NULLIF(SUM(installs) FILTER (WHERE d30_retained IS NOT NULL), 0) AS d30_retention
-- FROM cohorts
```

Retention is not a paid metric, so Organic may be included. Label it clearly, or split
Paid vs Organic.

### ARPDAU (source: `daily_kpis`)

Average revenue per daily active user, all users (paid + organic):

```sql
SUM(revenue) * 1.0 / NULLIF(SUM(dau), 0)                      AS arpdau
-- FROM daily_kpis
```

### Payer conversion

**Cohort payer conversion (D7)**, the default meaning in this project. It is the share of
installers who paid within 7 days, and works for mature D7 cohorts only:

```sql
SUM(payers_d7) * 1.0 / NULLIF(SUM(installs) FILTER (WHERE payers_d7 IS NOT NULL), 0) AS payer_conversion_d7
-- FROM cohorts
```

**Daily payer rate** is the share of daily actives who paid that day. It is game-wide, by platform only:

```sql
SUM(payers) * 1.0 / NULLIF(SUM(dau), 0)                       AS daily_payer_rate
-- FROM daily_kpis
```

Say which one you're reporting.

## House rules for every analysis/report

1. **Validate totals before reporting.** Before giving any number, check that it reconciles:
   - Breakdown rows sum to the stated total (spend, installs, revenue, DAU).
   - `ua_spend` installs aggregated to cohort grain equal `cohorts.installs` for the slice
     being analysed.
   - Join row counts match expectations (no creative fan-out). Show the check or state that
     it passed.
2. **Use `NULLIF(denominator, 0)` in every division**, with no exceptions.
3. **State the date range in every report.** Give it as install-date or activity-date range
   (e.g. "installs 2026-06-01 → 2026-08-22, D7-mature cohorts"). If different metrics use
   different windows because of maturity, list each window.
4. **Exclude immature cohorts.** Drop cohorts too recent to have D7/D30 data (NULL values)
   from D7/D30 metrics, from **both numerator and denominator**. Filter on the metric column
   being `IS NOT NULL`. Never treat NULL as 0. Mature windows as of 2026-08-29:
   D1 ≤ 2026-08-28, D7 ≤ 2026-08-22, D30 ≤ 2026-07-30.
5. **Exclude Organic from paid metrics:** CPI, ROAS, CTR, IPM always use
   `WHERE channel <> 'Organic'`. Organic has zero spend, impressions and clicks, so it would
   lower CPI and dilute CTR/IPM.
6. Compute ratios from summed components at the reporting grain, never as averages of ratios.
