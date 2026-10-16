-- Weekly paid series for the structural-issues section: the report week and the 7 weeks
-- before it (8 Mon-Sun weeks), by channel, by country and in total.
-- Sources: cohorts + ua_spend aggregated to cohort grain FIRST (no creative fan-out), so spend,
-- installs and cohort revenue share one grain. Installs reconcile with ua_spend (check_reconcile).
-- Ratios are built in the script from these summed components; ROAS components only include
-- cohorts mature for that metric, in numerator AND denominator (CLAUDE.md rule 4).
-- The script derives "rest of paid" per entity as total minus entity (no self-comparison).
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
    CAST(DATE_TRUNC('week', c.install_date) AS DATE) AS week_start,  -- ISO weeks start Monday
    c.*, s.spend
  FROM cohorts c
  JOIN spend s USING (install_date, channel, campaign, country, platform)
  CROSS JOIN p
  WHERE c.channel <> 'Organic'
    AND c.install_date BETWEEN p.cur_start - 49 AND p.cur_start + 6
)
SELECT
  CASE WHEN GROUPING(channel) = 0 THEN 'channel'
       WHEN GROUPING(country) = 0 THEN 'country'
       ELSE 'total' END                                               AS dim,
  COALESCE(channel, country, 'All paid')                              AS key,
  week_start,
  COUNT(DISTINCT install_date)                                        AS days,
  SUM(spend)                                                          AS spend,
  SUM(installs)                                                       AS installs,
  SUM(revenue_d7)  FILTER (WHERE revenue_d7  IS NOT NULL)             AS revenue_d7,
  SUM(spend)       FILTER (WHERE revenue_d7  IS NOT NULL)             AS spend_d7,
  SUM(revenue_d30) FILTER (WHERE revenue_d30 IS NOT NULL)             AS revenue_d30,
  SUM(spend)       FILTER (WHERE revenue_d30 IS NOT NULL)             AS spend_d30,
  MAX(install_date) FILTER (WHERE revenue_d30 IS NOT NULL)            AS d30_max_install_date
FROM c
GROUP BY GROUPING SETS ((week_start), (week_start, channel), (week_start, country))
ORDER BY dim, key, week_start;
