WITH "aggregated" AS (
  SELECT
    "t1"."region" AS "g0",
    GROUPING("t1"."region") AS "is_total",
    COUNT(DISTINCT "t0"."order_id") AS "m0"
  FROM "fact_sales" AS "t0"
  LEFT JOIN "dim_store" AS "t1" ON "t0"."store_id" = "t1"."store_id"
  GROUP BY GROUPING SETS (("t1"."region"), ())
)
SELECT
  CASE WHEN "q"."is_total" = 1 THEN 'Total' ELSE CAST("q"."g0" AS VARCHAR) END AS "region",
  "q"."m0" AS "order_count"
FROM "aggregated" AS "q"
ORDER BY "q"."is_total" ASC, "q"."g0" ASC NULLS LAST;
