WITH "aggregated" AS (
  SELECT
    "t2"."region" AS "g0",
    GROUPING("t2"."region") AS "is_total",
    SUM("t0"."revenue") FILTER (WHERE CAST("t1"."fiscal_year" AS TEXT) = E'2025') AS "m0",
    SUM("t0"."revenue") FILTER (WHERE CAST("t1"."fiscal_year" AS TEXT) = E'2026') AS "m1"
  FROM "fact_sales" AS "t0"
  LEFT JOIN "dim_calendar" AS "t1" ON "t0"."order_date" = "t1"."date"
  LEFT JOIN "dim_store" AS "t2" ON "t0"."store_id" = "t2"."store_id"
  WHERE CAST("t1"."fiscal_year" AS TEXT) IN (E'2025', E'2026')
  GROUP BY GROUPING SETS (("t2"."region"), ())
)
SELECT
  CASE WHEN "q"."is_total" = 1 THEN E'Total' ELSE CAST("q"."g0" AS TEXT) END AS "region",
  "q"."m0" AS "total_revenue_2025",
  "q"."m1" AS "total_revenue_2026",
  ("q"."m1" - "q"."m0") AS "total_revenue_delta",
  100.0 * ("q"."m1" - "q"."m0") / NULLIF("q"."m0", 0) AS "total_revenue_pct_change"
FROM "aggregated" AS "q"
ORDER BY "q"."is_total" ASC, "q"."g0" ASC NULLS LAST;
