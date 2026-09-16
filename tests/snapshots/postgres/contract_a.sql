WITH "aggregated" AS (
  SELECT
    SUM("t0"."revenue") FILTER (WHERE "t0"."channel" = E'Online') AS "m0",
    SUM("t0"."revenue") AS "m1"
  FROM "fact_sales" AS "t0"
  LEFT JOIN "dim_calendar" AS "t1" ON "t0"."order_date" = "t1"."date"
  WHERE "t1"."fiscal_year" = 2026
)
SELECT
  "q"."m0" AS "online_rev",
  "q"."m1" AS "total_revenue"
FROM "aggregated" AS "q";
