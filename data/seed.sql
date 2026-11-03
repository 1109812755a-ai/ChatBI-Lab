INSERT INTO dim_date (date_key, full_date, month_start, year, month) VALUES
    (20261003, '2026-10-03', '2026-10-01', 2026, 10),
    (20261005, '2026-10-05', '2026-10-01', 2026, 10),
    (20261012, '2026-10-12', '2026-10-01', 2026, 10),
    (20261021, '2026-10-21', '2026-10-01', 2026, 10);

INSERT INTO dim_store (store_key, store_code, store_name, region) VALUES
    (1, 'S-NORTH-01', '北城一店', '华北'),
    (2, 'S-SOUTH-01', '南城一店', '华南');

INSERT INTO dim_product (product_key, sku, product_name, category) VALUES
    (101, 'SKU-APPLE', '红富士苹果', '水果'),
    (102, 'SKU-MILK', '纯牛奶', '乳品'),
    (103, 'SKU-BREAD', '全麦面包', '烘焙');

INSERT INTO fact_order (order_id, store_key, order_date_key, status, gmv_amount) VALUES
    ('O-1001', 1, 20261003, 'completed', 100.00),
    ('O-1002', 1, 20261005, 'completed', 50.00),
    ('O-1003', 1, 20261012, 'cancelled', 80.00),
    ('O-2001', 2, 20261021, 'completed', 70.00);

INSERT INTO fact_order_line (order_line_id, order_id, product_key, quantity) VALUES
    ('L-1001-A', 'O-1001', 101, 2),
    ('L-1001-B', 'O-1001', 102, 1),
    ('L-1002-A', 'O-1002', 103, 5),
    ('L-1003-A', 'O-1003', 101, 4),
    ('L-2001-A', 'O-2001', 101, 2),
    ('L-2001-B', 'O-2001', 103, 1);
