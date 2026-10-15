-- Organic installs, current vs previous week (context only; not a paid metric).
WITH p AS (SELECT CAST($week_start AS DATE) AS cur_start)
SELECT
  CASE WHEN u.date >= p.cur_start THEN 'cur' ELSE 'prev' END AS period,
  SUM(u.installs)                                             AS installs
FROM ua_spend u, p
WHERE u.channel = 'Organic'
  AND u.date BETWEEN p.cur_start - 7 AND p.cur_start + 6
GROUP BY ALL
ORDER BY period;
