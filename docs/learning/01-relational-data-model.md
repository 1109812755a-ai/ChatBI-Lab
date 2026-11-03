# 1. 零售数据表、指标与粒度

本章先从数据库里的表开始。业务人员说“门店”“订单”“商品”，数据库则把它们保存成行、列和键。要让 Agent 正确问数，必须先知道每张表的一行代表什么。

本章对应文件：

- 表结构：[`data/schema.sql`](../../data/schema.sql)
- 模拟数据：[`data/seed.sql`](../../data/seed.sql)
- 指标口径和预期结果：[`docs/domain/competency-questions.md`](../domain/competency-questions.md)、[`data/expected-results.json`](../../data/expected-results.json)

## 表与键

项目用三张维度表描述分析对象：

- `dim_store`：每行一个门店。
- `dim_product`：每行一个商品。
- `dim_date`：每行一个自然日。

两张事实表保存业务记录：

- `fact_order`：每行一个订单，主键是 `order_id`。订单总额 `gmv_amount` 位于这一粒度。
- `fact_order_line`：每行是某订单中的一个商品明细，主键是 `order_line_id`，通过 `order_id` 关联订单，通过 `product_key` 关联商品。

外键表达可连接的记录。例如 `fact_order.store_key` 指向 `dim_store.store_key`。连接事实表时，需要同时检查关系是否正确、结果的粒度是否仍然适用于待计算指标。

## 指标必须带口径和粒度

本项目的模拟指标定义如下：

| 指标 | 来源和计算 | 原生粒度 |
|---|---|---|
| GMV | 完成订单的 `fact_order.gmv_amount` 求和 | 订单 |
| 订单数 | 完成订单的 `order_id` 去重计数 | 订单 |
| 销量 | 完成订单对应的明细 `quantity` 求和 | 订单明细 |

这里的 GMV 是教学用定义：扣除商品行折扣，未扣运费和退款。不同零售企业可能有不同口径，Agent 必须使用项目显式定义，不能自行猜测。

## 粒度不匹配会重复计算

样例订单 `O-1001` 的 GMV 是 100，但它有两条商品明细。若把订单与明细连接后直接汇总订单金额，这笔 GMV 会出现两次：

```sql
SELECT s.store_code, SUM(o.gmv_amount) AS incorrect_gmv
FROM fact_order AS o
JOIN fact_order_line AS l ON l.order_id = o.order_id
JOIN dim_store AS s ON s.store_key = o.store_key
WHERE o.status = 'completed'
  AND o.order_date_key BETWEEN 20261001 AND 20261031
GROUP BY s.store_code;
```

错误结果会是北城一店 250、南城一店 140；正确 GMV 应分别为 150 和 70。原因是 `gmv_amount` 属于订单粒度，而 Join 后的结果变成订单明细粒度。

## 在各自粒度先聚合，再合并指标

GMV 和订单数从订单表计算，销量从订单明细表计算。先分别按门店汇总，再合并结果：

```sql
WITH gmv AS (
    SELECT store_key, SUM(gmv_amount) AS gmv
    FROM fact_order
    WHERE status = 'completed'
      AND order_date_key BETWEEN 20261001 AND 20261031
    GROUP BY store_key
),
order_counts AS (
    SELECT store_key, COUNT(DISTINCT order_id) AS order_count
    FROM fact_order
    WHERE status = 'completed'
      AND order_date_key BETWEEN 20261001 AND 20261031
    GROUP BY store_key
),
units AS (
    SELECT o.store_key, SUM(l.quantity) AS units_sold
    FROM fact_order AS o
    JOIN fact_order_line AS l ON l.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.order_date_key BETWEEN 20261001 AND 20261031
    GROUP BY o.store_key
)
SELECT s.store_code, g.gmv, c.order_count, u.units_sold
FROM gmv AS g
JOIN order_counts AS c USING (store_key)
JOIN units AS u USING (store_key)
JOIN dim_store AS s USING (store_key)
ORDER BY s.store_code;
```

预期结果：北城一店 GMV 150、订单数 2、销量 8；南城一店 GMV 70、订单数 1、销量 3。可用下面的命令重建本地数据库，再把查询粘贴到 SQLite 客户端执行：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

## 对 Agent 的意义

“按门店看 GMV 和销量”不是单纯把词替换成字段。Agent 必须知道 GMV 在订单表、销量在明细表，两个指标粒度不同；它应先读取语义模型中的口径和映射，再选择能避免重复计算的查询计划。后续章节会说明本体如何表达这些业务关系。
