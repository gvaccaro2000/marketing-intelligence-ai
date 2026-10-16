-- Game-wide KPIs (all users, paid + organic), current vs previous week, by activity date.
-- dau/payers are daily distinct counts: sums are user-days, used only inside ratios
-- (avg_dau divides user-days by the number of days, which is a daily average, not uniques).
WITH p AS (SELECT CAST($week_start AS DATE) AS cur_start)
SELECT
  CASE WHEN k.date >= p.cur_start THEN 'cur' ELSE 'prev' END AS period,
  COUNT(DISTINCT k.date)                                      AS days,
  SUM(k.revenue)                                              AS revenue,
  SUM(k.dau) * 1.0 / NULLIF(COUNT(DISTINCT k.date), 0)        AS avg_dau,
  SUM(k.revenue) * 1.0 / NULLIF(SUM(k.dau), 0)                AS arpdau,
  SUM(k.payers) * 1.0 / NULLIF(SUM(k.dau), 0)                 AS daily_payer_rate
FROM daily_kpis k, p
WHERE k.date BETWEEN p.cur_start - 7 AND p.cur_start + 6
GROUP BY ALL
ORDER BY period;
