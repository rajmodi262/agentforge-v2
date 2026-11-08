-- Phantom Hunter — analytics in plain SQL
-- Runs against the app database (SQLite in dev). Plain SQL with CTEs, CASE and window functions;
-- SQLite-only bits are the date helper strftime() (Postgres: to_char) and booleans stored as 1/0.
-- `python -m app.phantom.sql_report` executes each block and writes analytics/SQL_RESULTS.md.
-- Blocks are separated by "-- name:" lines; the line after it is the business question.

-- name: pipeline_headline
-- How much announced capacity is really likely to be built?
SELECT COUNT(*)                                                   AS projects_with_mw,
       ROUND(SUM(capacity_mw))                                    AS announced_mw,
       ROUND(SUM(capacity_mw * reality_score))                    AS reality_mw,
       ROUND(SUM(capacity_mw * (1 - reality_score)))              AS phantom_mw,
       ROUND(100.0 * SUM(capacity_mw * reality_score) / SUM(capacity_mw), 1) AS reality_pct
FROM ph_projects
WHERE capacity_mw IS NOT NULL;

-- name: evidence_ladder_funnel
-- Where are projects really, and how much capacity sits at each rung?
SELECT CASE stage WHEN 0 THEN '0 ANNOUNCED' WHEN 1 THEN '1 SITE' WHEN 2 THEN '2 APPROVED'
                  WHEN 3 THEN '3 POWER' WHEN 4 THEN '4 BUILDING' ELSE '5 LIVE' END AS stage,
       COUNT(*)                                     AS projects,
       ROUND(SUM(COALESCE(capacity_mw, 0)))         AS announced_mw,
       ROUND(AVG(reality_score) * 100, 1)           AS avg_reality_pct
FROM ph_projects
GROUP BY stage
ORDER BY stage;

-- name: phantom_gap_by_state
-- Which states/regions carry the biggest gap between announced and likely capacity?
SELECT COALESCE(state, '(place not stated)') || ', ' || country AS region,
       COUNT(*)                                                 AS projects,
       ROUND(SUM(capacity_mw))                                  AS announced_mw,
       ROUND(SUM(capacity_mw * reality_score))                  AS reality_mw,
       ROUND(SUM(capacity_mw * (1 - reality_score)))            AS phantom_mw,
       ROUND(100.0 * SUM(capacity_mw * reality_score) / SUM(capacity_mw), 1) AS reality_pct
FROM ph_projects
WHERE capacity_mw IS NOT NULL
GROUP BY state, country
HAVING SUM(capacity_mw) >= 500
ORDER BY phantom_mw DESC
LIMIT 10;

-- name: developer_league_table
-- Which developers announce the most — and how much of it looks real? (window function: rank)
WITH dev AS (
    SELECT developer,
           COUNT(*)                                AS projects,
           SUM(capacity_mw)                        AS announced_mw,
           SUM(capacity_mw * reality_score)        AS reality_mw
    FROM ph_projects
    WHERE developer IS NOT NULL AND capacity_mw IS NOT NULL
    GROUP BY developer
)
SELECT RANK() OVER (ORDER BY announced_mw DESC)       AS rank_announced,
       developer, projects,
       ROUND(announced_mw)                            AS announced_mw,
       ROUND(reality_mw)                              AS reality_mw,
       ROUND(100.0 * reality_mw / announced_mw, 1)    AS reality_pct,
       RANK() OVER (ORDER BY reality_mw DESC)         AS rank_real
FROM dev
ORDER BY announced_mw DESC
LIMIT 12;

-- name: market_share_by_country
-- Each developer's share of its country's reality-weighted pipeline (window: partitioned sum).
WITH d AS (
    SELECT country, developer, SUM(capacity_mw * reality_score) AS reality_mw
    FROM ph_projects
    WHERE developer IS NOT NULL AND capacity_mw IS NOT NULL
    GROUP BY country, developer
)
SELECT country, developer,
       ROUND(reality_mw)                                                            AS reality_mw,
       ROUND(100.0 * reality_mw / SUM(reality_mw) OVER (PARTITION BY country), 1)   AS share_pct,
       ROW_NUMBER() OVER (PARTITION BY country ORDER BY reality_mw DESC)            AS rnk
FROM d
ORDER BY country, rnk
LIMIT 20;

-- name: sales_pipeline_power
-- Who should a power / IPP sales team call? Likely-real projects, no energy partner yet, before construction.
SELECT name, developer, COALESCE(state, country) AS location,
       ROUND(capacity_mw)              AS capacity_mw,
       ROUND(reality_score * 100)      AS reality_pct,
       CASE stage WHEN 1 THEN 'SITE' WHEN 2 THEN 'APPROVED' WHEN 3 THEN 'POWER' ELSE 'ANNOUNCED' END AS stage,
       n_sources
FROM ph_projects
WHERE power_partner IS NULL
  AND stage <= 3
  AND reality_score >= 0.45
  AND capacity_mw >= 50
ORDER BY reality_score * capacity_mw DESC
LIMIT 10;

-- name: evidence_strength
-- Does more independent coverage go with a higher reality score? (sanity check on the scorer)
SELECT CASE WHEN n_sources = 1 THEN '1 source' WHEN n_sources = 2 THEN '2 sources'
            WHEN n_sources <= 4 THEN '3–4 sources' ELSE '5+ sources' END AS coverage,
       COUNT(*)                              AS projects,
       ROUND(AVG(reality_score) * 100, 1)    AS avg_reality_pct,
       ROUND(AVG(stage), 2)                  AS avg_stage
FROM ph_projects
GROUP BY 1
ORDER BY MIN(n_sources);

-- name: source_quality
-- Which publishers feed the most verified evidence, and how often is it headline-only?
SELECT a.source,
       COUNT(*)                                                              AS evidence_items,
       COUNT(DISTINCT e.project_id)                                          AS projects,
       ROUND(100.0 * SUM(CASE WHEN a.text_kind = 'summary' THEN 1 ELSE 0 END) / COUNT(*), 0) AS headline_only_pct
FROM ph_evidence e
JOIN ph_articles a ON a.id = e.article_id
GROUP BY a.source
ORDER BY evidence_items DESC
LIMIT 10;

-- name: scout_funnel_by_feed
-- How productive is each search feed, from article to verified evidence?
SELECT a.feed,
       COUNT(DISTINCT a.id)                                              AS articles,
       SUM(CASE WHEN a.relevant = 1 THEN 1 ELSE 0 END)                   AS relevant,
       SUM(CASE WHEN a.text_kind = 'full' THEN 1 ELSE 0 END)             AS full_text,
       (SELECT COUNT(*) FROM ph_evidence e JOIN ph_articles x ON x.id = e.article_id WHERE x.feed = a.feed) AS evidence_items
FROM ph_articles a
GROUP BY a.feed
ORDER BY articles DESC;

-- name: anomaly_summary
-- What is Anomaly Watch flagging, and how serious is it?
SELECT kind, severity, COUNT(*) AS projects
FROM ph_anomalies
GROUP BY kind, severity
ORDER BY projects DESC;

-- name: news_momentum
-- Is announcement activity accelerating? Verified evidence per quarter (last 8 quarters with data).
SELECT quarter, evidence_items,
       evidence_items - LAG(evidence_items) OVER (ORDER BY quarter) AS change_vs_prev
FROM (
    SELECT strftime('%Y', event_date) || '-Q' || ((CAST(strftime('%m', event_date) AS INTEGER) + 2) / 3) AS quarter,
           COUNT(*) AS evidence_items
    FROM ph_evidence
    WHERE event_date IS NOT NULL
    GROUP BY 1
)
ORDER BY quarter DESC
LIMIT 8;
