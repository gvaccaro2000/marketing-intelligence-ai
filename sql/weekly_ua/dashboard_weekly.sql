-- Weekly series for the dashboard export (scripts/export_dashboard_data.py): every complete
-- Mon-Sun week in the data, by channel, by country and in total.
-- Delivery (spend, installs, organic installs) comes from ua_spend by activity date.
-- D7 revenue + D7-mature spend come from cohorts joined to ua_spend aggregated to cohort grain
-- FIRST (no creative fan-out), with only D7-mature cohorts in numerator AND denominator.
-- join_spend / join_installs are the paid totals surviving the cohort join; the script checks
-- them against delivery (no fan-out, no dropped rows).
-- A week is complete when ua_spend has all 7 of its days. Organic is excluded from paid metrics;
-- its installs are reported separately as organic_installs.
WITH weeks AS (
  SELECT CAST(DATE_TRUNC('week', date) AS DATE) AS week_start  -- ISO weeks start Monday
  FROM (SELECT DISTINCT date FROM ua_spend)
  GROUP BY 1
  HAVING COUNT(*) = 7
),
delivery AS (
  SELECT CAST(DATE_TRUNC('week', date) AS DATE) AS week_start, channel, country,
         SUM(spend)    FILTER (WHERE channel <> 'Organic') AS spend,
         SUM(installs) FILTER (WHERE channel <> 'Organic') AS installs,
         SUM(installs) FILTER (WHERE channel = 'Organic')  AS organic_installs
  FROM ua_spend
  GROUP BY ALL
),
spend AS (
  SELECT date AS install_date, channel, campaign, country, platform,
         SUM(spend) AS spend
  FROM ua_spend
  WHERE channel <> 'Organic'
  GROUP BY ALL
),
quality AS (
  SELECT CAST(DATE_TRUNC('week', c.install_date) AS DATE) AS week_start, c.channel, c.country,
         SUM(c.revenue_d7) FILTER (WHERE c.revenue_d7 IS NOT NULL) AS d7_revenue,
         SUM(s.spend)      FILTER (WHERE c.revenue_d7 IS NOT NULL) AS d7_mature_spend,
         MAX(c.install_date) FILTER (WHERE c.revenue_d7 IS NOT NULL) AS d7_max_install_date,
         SUM(s.spend)      AS join_spend,
         SUM(c.installs)   AS join_installs
  FROM cohorts c
  JOIN spend s USING (install_date, channel, campaign, country, platform)
  WHERE c.channel <> 'Organic'
  GROUP BY ALL
),
base AS (
  SELECT d.week_start, d.channel, d.country,
         COALESCE(d.spend, 0)             AS spend,
         COALESCE(d.installs, 0)          AS installs,
         COALESCE(d.organic_installs, 0)  AS organic_installs,
         COALESCE(q.d7_revenue, 0)        AS d7_revenue,
         COALESCE(q.d7_mature_spend, 0)   AS d7_mature_spend,
         q.d7_max_install_date,
         COALESCE(q.join_spend, 0)        AS join_spend,
         COALESCE(q.join_installs, 0)     AS join_installs
  FROM delivery d
  JOIN weeks w USING (week_start)
  LEFT JOIN quality q USING (week_start, channel, country)
)
SELECT
  CASE WHEN GROUPING(channel) = 0 THEN 'channel'
       WHEN GROUPING(country) = 0 THEN 'country'
       ELSE 'total' END                                               AS dim,
  COALESCE(channel, country, 'All paid')                              AS key,
  week_start,
  SUM(spend)                                                          AS spend,
  SUM(installs)                                                       AS installs,
  SUM(spend) * 1.0 / NULLIF(SUM(installs), 0)                         AS cpi,
  SUM(d7_revenue)                                                     AS d7_revenue,
  SUM(d7_mature_spend)                                                AS d7_mature_spend,
  SUM(d7_revenue) * 1.0 / NULLIF(SUM(d7_mature_spend), 0)             AS roas_d7,
  SUM(organic_installs)                                               AS organic_installs,
  MAX(d7_max_install_date)                                            AS d7_max_install_date,
  SUM(join_spend)                                                     AS join_spend,
  SUM(join_installs)                                                  AS join_installs
FROM base
GROUP BY GROUPING SETS ((week_start), (week_start, channel), (week_start, country))
ORDER BY dim, key, week_start;
