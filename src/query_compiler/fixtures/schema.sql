CREATE TABLE dim_store (
    store_id TEXT PRIMARY KEY,
    store_name TEXT,
    region TEXT
);
CREATE TABLE dim_calendar (
    date DATE PRIMARY KEY,
    fiscal_year INTEGER,
    fiscal_quarter TEXT
);
CREATE TABLE fact_sales (
    -- Grain: one order line. Orders may have lines in different stores.
    order_id TEXT,
    order_date DATE,
    ship_date DATE,
    store_id TEXT,
    channel TEXT,
    revenue DOUBLE PRECISION
);

INSERT INTO dim_store VALUES
    ('S1', 'Downtown', 'North'),
    ('S2', 'Uptown', 'North'),
    ('S3', 'Riverside', 'South'),
    ('S4', 'Hilltop', 'West');

INSERT INTO fact_sales VALUES
    ('O-100', '2025-03-10', '2025-03-12', 'S1', 'Online', 100),
    ('O-101', '2025-04-02', '2025-04-04', 'S3', 'Retail', 200),
    ('O-102', '2025-06-15', '2025-06-17', 'S4', 'Online', 150),
    ('O-200', '2026-02-01', '2026-02-03', 'S1', 'Online', 120),
    ('O-201', '2026-02-11', '2026-02-13', 'S2', 'Retail', 80),
    ('O-202', '2026-03-05', '2026-03-07', 'S3', 'Online', 300),
    ('O-203', '2026-03-06', '2026-03-08', 'S1', 'Retail', 50),
    ('O-203', '2026-03-06', '2026-03-08', 'S3', 'Retail', 70),
    ('O-204', '2026-06-20', '2026-06-22', 'S4', 'Retail', 90);

-- The PDF asks for every date, but lists only order dates. Include ship dates too.
-- This is fixture setup, not compiler introspection. Fiscal/calendar years coincide here.
INSERT INTO dim_calendar
SELECT date, CAST(EXTRACT(YEAR FROM date) AS INTEGER),
       'Q' || CAST(EXTRACT(QUARTER FROM date) AS VARCHAR)
FROM (
    SELECT order_date AS date FROM fact_sales
    UNION
    SELECT ship_date AS date FROM fact_sales
) AS dates;
