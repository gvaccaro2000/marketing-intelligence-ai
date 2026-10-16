-- Reconciliation for the two report weeks (all channels incl. Organic for installs).
-- 1) ua_spend aggregated to cohort grain vs cohorts.installs, row for row (FULL JOIN
--    so rows missing on either side are caught).
-- 2) Spend surviving the cohort join (ROAS denominator) vs raw ua_spend paid spend.
WITH p AS (SELECT CAST($week_start AS DATE) AS cur_start),
u AS (
  SELECT date AS install_date, channel, campaign, country, platform,
         SUM(installs) AS ua_installs, SUM(spend) AS ua_spend
  FROM ua_spend, p
  WHERE date BETWEEN p.cur_start - 7 AND p.cur_start + 6
  GROUP BY ALL
),
c AS (
  SELECT install_date, channel, campaign, country, platform, installs AS cohort_installs
  FROM cohorts, p
  WHERE install_date BETWEEN p.cur_start - 7 AND p.cur_start + 6
),
j AS (
  SELECT
    COALESCE(u.install_date, c.install_date) AS install_date,
    COALESCE(u.channel, c.channel)           AS channel,
    u.ua_installs, u.ua_spend, c.cohort_installs
  FROM u FULL OUTER JOIN c USING (install_date, channel, campaign, country, platform)
)
SELECT
  CASE WHEN install_date >= (SELECT cur_start FROM p) THEN 'cur' ELSE 'prev' END AS period,
  COUNT(*)                                                         AS grain_rows,
  COUNT(*) FILTER (WHERE ua_installs IS NULL)                      AS rows_only_in_cohorts,
  COUNT(*) FILTER (WHERE cohort_installs IS NULL)                  AS rows_only_in_ua_spend,
  COUNT(*) FILTER (WHERE ua_installs <> cohort_installs)           AS rows_install_mismatch,
  SUM(ua_installs)                                                 AS ua_installs,
  SUM(cohort_installs)                                             AS cohort_installs,
  SUM(ua_spend) FILTER (WHERE channel <> 'Organic')                AS ua_paid_spend,
  SUM(ua_spend) FILTER (WHERE channel <> 'Organic'
                          AND cohort_installs IS NOT NULL)         AS joined_paid_spend,
  SUM(ua_spend) FILTER (WHERE channel = 'Organic')                 AS organic_spend
FROM j
GROUP BY ALL
ORDER BY period;
