-- Data-quality checks for the two report weeks. Each row is one check; `failures` must be 0.
WITH p AS (
  SELECT CAST($week_start AS DATE) AS cur_start, CAST($as_of AS DATE) AS as_of
),
u AS (SELECT u.* FROM ua_spend u, p WHERE u.date BETWEEN p.cur_start - 7 AND p.cur_start + 6),
c AS (SELECT c.* FROM cohorts c, p WHERE c.install_date BETWEEN p.cur_start - 7 AND p.cur_start + 6),
k AS (SELECT k.* FROM daily_kpis k, p WHERE k.date BETWEEN p.cur_start - 7 AND p.cur_start + 6)
SELECT 'ua_spend: NULL in any column' AS check_name,
       COUNT(*) FILTER (WHERE date IS NULL OR channel IS NULL OR campaign IS NULL OR country IS NULL
                          OR platform IS NULL OR creative_id IS NULL OR spend IS NULL
                          OR impressions IS NULL OR clicks IS NULL OR installs IS NULL) AS failures
FROM u
UNION ALL
SELECT 'ua_spend: negative values or clicks > impressions',
       COUNT(*) FILTER (WHERE spend < 0 OR impressions < 0 OR clicks < 0 OR installs < 0
                          OR clicks > impressions) FROM u
UNION ALL
SELECT 'ua_spend: Organic with spend/impressions/clicks',
       COUNT(*) FILTER (WHERE channel = 'Organic' AND (spend <> 0 OR impressions <> 0 OR clicks <> 0)) FROM u
UNION ALL
SELECT 'ua_spend: paid row with spend but 0 impressions',
       COUNT(*) FILTER (WHERE channel <> 'Organic' AND spend > 0 AND impressions = 0) FROM u
UNION ALL
SELECT 'ua_spend: missing days (expect 14)',
       14 - COUNT(DISTINCT date) FROM u
UNION ALL
SELECT 'cohorts: NULL keys / installs / revenue_d0',
       COUNT(*) FILTER (WHERE install_date IS NULL OR channel IS NULL OR campaign IS NULL
                          OR country IS NULL OR platform IS NULL OR installs IS NULL
                          OR revenue_d0 IS NULL) FROM c
UNION ALL
SELECT 'cohorts: NULL in a mature D1/D7 metric',
       COUNT(*) FILTER (WHERE (install_date <= as_of - 1 AND d1_retained IS NULL)
                           OR (install_date <= as_of - 7 AND (d7_retained IS NULL OR revenue_d7 IS NULL
                                                              OR payers_d7 IS NULL)))
FROM c, p
UNION ALL
SELECT 'cohorts: value present for an immature cohort',
       COUNT(*) FILTER (WHERE (install_date > as_of - 1 AND d1_retained IS NOT NULL)
                           OR (install_date > as_of - 7 AND (d7_retained IS NOT NULL OR revenue_d7 IS NOT NULL
                                                             OR payers_d7 IS NOT NULL)))
FROM c, p
UNION ALL
SELECT 'cohorts: retained/payers > installs or revenue not cumulative',
       COUNT(*) FILTER (WHERE d1_retained > installs OR d7_retained > installs OR payers_d7 > installs
                           OR revenue_d7 < revenue_d0 OR revenue_d0 < 0) FROM c
UNION ALL
SELECT 'daily_kpis: NULLs, negatives, or payers > dau',
       COUNT(*) FILTER (WHERE dau IS NULL OR revenue IS NULL OR payers IS NULL
                           OR dau < 0 OR revenue < 0 OR payers > dau) FROM k
UNION ALL
SELECT 'daily_kpis: missing date x platform rows (expect 28)',
       28 - COUNT(*) FROM k;
