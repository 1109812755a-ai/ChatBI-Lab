PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date TEXT NOT NULL UNIQUE,
    month_start TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_store (
    store_key INTEGER PRIMARY KEY,
    store_code TEXT NOT NULL UNIQUE,
    store_name TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_key INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL
);

-- Grain: one row per order. gmv_amount is net of line discounts, before shipping/refunds.
CREATE TABLE IF NOT EXISTS fact_order (
    order_id TEXT PRIMARY KEY,
    store_key INTEGER NOT NULL REFERENCES dim_store(store_key),
    order_date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
    status TEXT NOT NULL CHECK (status IN ('completed', 'cancelled')),
    gmv_amount NUMERIC NOT NULL CHECK (gmv_amount >= 0)
);

-- Grain: one row per product line in an order.
CREATE TABLE IF NOT EXISTS fact_order_line (
    order_line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES fact_order(order_id),
    product_key INTEGER NOT NULL REFERENCES dim_product(product_key),
    quantity INTEGER NOT NULL CHECK (quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_fact_order_store_date
    ON fact_order(store_key, order_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_order_line_order
    ON fact_order_line(order_id);
