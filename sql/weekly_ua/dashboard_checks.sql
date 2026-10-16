-- Checks for the dashboard export over every complete week (all channels incl. Organic).
-- 1) ua_spend aggregated to cohort grain vs cohorts.installs, row for row (FULL JOIN so rows
--    missing on either side are caught).
-- 2) D7 maturity: revenue_d7 present for every cohort on or before $as_of - 7 and absent after.
WITH weeks AS (
  SELECT CAST(DATE_TRUNC('week', date) AS DATE) AS week_start
  FROM (SELECT DISTINCT date FROM ua_spend)
  GROUP BY 1
  HAVING COUNT(*) = 7
),
u AS (
  SELECT date AS install_date, channel, campaign, country, platform, SUM(installs) AS ua_installs
  FROM ua_spend
  WHERE CAST(DATE_TRUNC('week', date) AS DATE) IN (SELECT week_start FROM weeks)
  GROUP BY ALL
),
c AS (
  SELECT install_date, channel, campaign, country, platform, installs AS cohort_installs,
         revenue_d7
  FROM cohorts
  WHERE CAST(DATE_TRUNC('week', install_date) AS DATE) IN (SELECT week_start FROM weeks)
),
j AS (
  SELECT u.ua_installs, c.cohort_installs
  FROM u FULL OUTER JOIN c USING (install_date, channel, campaign, country, platform)
)
SELECT
  (SELECT COUNT(*) FROM weeks)                                              AS complete_weeks,
  (SELECT MIN(week_start) FROM weeks)                                       AS first_week,
  (SELECT MAX(week_start) FROM weeks)                                       AS last_week,
  (SELECT COUNT(*) FROM j)                                                  AS grain_rows,
  (SELECT COUNT(*) FROM j WHERE ua_installs IS NULL)                        AS rows_only_in_cohorts,
  (SELECT COUNT(*) FROM j WHERE cohort_installs IS NULL)                    AS rows_only_in_ua_spend,
  (SELECT COUNT(*) FROM j WHERE ua_installs <> cohort_installs)             AS rows_install_mismatch,
  (SELECT SUM(ua_installs) FROM j)                                          AS ua_installs,
  (SELECT SUM(cohort_installs) FROM j)                                      AS cohort_installs,
  (SELECT COUNT(*) FROM c
    WHERE install_date <= CAST($as_of AS DATE) - 7 AND revenue_d7 IS NULL)  AS d7_missing_mature,
  (SELECT COUNT(*) FROM c
    WHERE install_date >  CAST($as_of AS DATE) - 7 AND revenue_d7 IS NOT NULL) AS d7_present_immature;
