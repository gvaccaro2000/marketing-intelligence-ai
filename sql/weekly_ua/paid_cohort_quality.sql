-- Paid cohort quality, current vs previous install week.
-- Sources: cohorts + ua_spend aggregated to cohort grain FIRST (no creative fan-out).
-- Each ratio only uses cohorts mature for that metric, in numerator AND denominator
-- (CLAUDE.md rule 4). Organic excluded: it has no spend, and this is a paid report.
WITH p AS (
  SELECT CAST($week_start AS DATE) AS cur_start
),
spend AS (
  SELECT date AS install_date, channel, campaign, country, platform,
         SUM(spend) AS spend
  FROM ua_spend
  WHERE channel <> 'Organic'
  GROUP BY ALL
),
c AS (
  SELECT
    CASE WHEN c.install_date >= p.cur_start THEN 'cur' ELSE 'prev' END AS period,
    c.*, s.spend
  FROM cohorts c
  JOIN spend s USING (install_date, channel, campaign, country, platform)
  CROSS JOIN p
  WHERE c.channel <> 'Organic'
    AND c.install_date BETWEEN p.cur_start - 7 AND p.cur_start + 6
)
SELECT
  CASE WHEN GROUPING(channel) = 0 THEN 'channel'
       WHEN GROUPING(country) = 0 THEN 'country'
       ELSE 'total' END                                                       AS dim,
  COALESCE(channel, country, 'All paid')                                      AS key,
  period,
  SUM(installs)                                                               AS installs,
  SUM(spend)                                                                  AS spend,
  -- maturity windows actually used (for the date-range statement in the report)
  MAX(install_date) FILTER (WHERE d1_retained IS NOT NULL)                    AS d1_max_install_date,
  MAX(install_date) FILTER (WHERE d7_retained IS NOT NULL)                    AS d7_max_install_date,
  SUM(d1_retained) * 1.0
    / NULLIF(SUM(installs) FILTER (WHERE d1_retained IS NOT NULL), 0)         AS d1_retention,
  SUM(d7_retained) * 1.0
    / NULLIF(SUM(installs) FILTER (WHERE d7_retained IS NOT NULL), 0)         AS d7_retention,
  SUM(payers_d7) * 1.0
    / NULLIF(SUM(installs) FILTER (WHERE payers_d7 IS NOT NULL), 0)           AS payer_conversion_d7,
  SUM(revenue_d0) * 1.0 / NULLIF(SUM(spend), 0)                               AS roas_d0,
  SUM(revenue_d7) FILTER (WHERE revenue_d7 IS NOT NULL) * 1.0
    / NULLIF(SUM(spend) FILTER (WHERE revenue_d7 IS NOT NULL), 0)             AS roas_d7,
  SUM(revenue_d7) FILTER (WHERE revenue_d7 IS NOT NULL)                       AS revenue_d7_mature,
  SUM(spend) FILTER (WHERE revenue_d7 IS NOT NULL)                            AS spend_d7_mature
FROM c
GROUP BY GROUPING SETS ((period), (period, channel), (period, country))
ORDER BY dim, key, period;
