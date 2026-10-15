-- Paid delivery metrics, current vs previous week, by activity date.
-- Source: ua_spend. Organic excluded (CLAUDE.md rule 5).
WITH p AS (
  SELECT CAST($week_start AS DATE) AS cur_start
),
base AS (
  SELECT
    CASE WHEN u.date >= p.cur_start THEN 'cur' ELSE 'prev' END AS period,
    u.channel, u.country, u.spend, u.impressions, u.clicks, u.installs
  FROM ua_spend u, p
  WHERE u.channel <> 'Organic'
    AND u.date BETWEEN p.cur_start - 7 AND p.cur_start + 6
)
SELECT
  CASE WHEN GROUPING(channel) = 0 THEN 'channel'
       WHEN GROUPING(country) = 0 THEN 'country'
       ELSE 'total' END                                    AS dim,
  COALESCE(channel, country, 'All paid')                   AS key,
  period,
  SUM(spend)                                               AS spend,
  SUM(installs)                                            AS installs,
  SUM(impressions)                                         AS impressions,
  SUM(clicks)                                              AS clicks,
  SUM(spend) * 1.0 / NULLIF(SUM(installs), 0)              AS cpi,
  SUM(clicks) * 1.0 / NULLIF(SUM(impressions), 0)          AS ctr,
  SUM(installs) * 1000.0 / NULLIF(SUM(impressions), 0)     AS ipm
FROM base
GROUP BY GROUPING SETS ((period), (period, channel), (period, country))
ORDER BY dim, key, period;
