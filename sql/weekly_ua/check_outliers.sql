-- Outlier scan: each paid channel-day (and channel x country-day) in the current week vs
-- that series' trailing 28 days before the week. Robust z = (x - median) / (1.4826 * MAD).
-- Flags |z| >= 3.5 on spend, installs and CPI. Returned rows are flags, not necessarily errors.
WITH p AS (SELECT CAST($week_start AS DATE) AS cur_start),
daily AS (
  SELECT 'channel' AS level, channel, 'all' AS country, date,
         SUM(spend) AS spend, SUM(installs) AS installs,
         SUM(spend) * 1.0 / NULLIF(SUM(installs), 0) AS cpi
  FROM ua_spend WHERE channel <> 'Organic' GROUP BY ALL
  UNION ALL
  SELECT 'channel_country', channel, country, date,
         SUM(spend), SUM(installs), SUM(spend) * 1.0 / NULLIF(SUM(installs), 0)
  FROM ua_spend WHERE channel <> 'Organic' GROUP BY ALL
),
long AS (
  UNPIVOT daily ON spend, installs, cpi INTO NAME metric VALUE value
),
base AS (
  SELECT l.level, l.channel, l.country, l.metric,
         MEDIAN(l.value) AS med,
         COUNT(*)        AS n_days
  FROM long l, p
  WHERE l.date BETWEEN p.cur_start - 28 AND p.cur_start - 1
  GROUP BY ALL
),
mad AS (
  SELECT l.level, l.channel, l.country, l.metric,
         MEDIAN(ABS(l.value - b.med)) AS mad
  FROM long l
  JOIN base b USING (level, channel, country, metric)
  CROSS JOIN p
  WHERE l.date BETWEEN p.cur_start - 28 AND p.cur_start - 1
  GROUP BY ALL
),
scored AS (
  SELECT l.level, l.channel, l.country, l.date, l.metric, l.value, b.med AS baseline_median,
         (l.value - b.med) / NULLIF(1.4826 * m.mad, 0) AS robust_z
  FROM long l
  JOIN base b USING (level, channel, country, metric)
  JOIN mad  m USING (level, channel, country, metric)
  CROSS JOIN p
  WHERE l.date BETWEEN p.cur_start AND p.cur_start + 6
    AND b.n_days >= 14
)
SELECT *
FROM scored
WHERE ABS(robust_z) >= 3.5
ORDER BY ABS(robust_z) DESC;
