# Retail domain scope and competency questions

This project is a local retail data-agent prototype. Its first slice answers questions about orders, order lines, products, stores, and time. All data and metric policies below are synthetic teaching examples, not universal retail accounting rules.

## Questions the first slice must answer

1. “按门店看上个月 GMV 和销量。” Return one row per store and month, with GMV and units sold.
2. “上个月每家门店有多少有效订单？” Return distinct completed-order counts by store for the requested period.
3. “GMV 怎么定义、来自哪些字段？” Return the selected metric definition, data grain, source mapping, and model version.
4. “按商品看 GMV” when no product-level GMV allocation is defined. Explain that this combination is unsupported rather than inventing an allocation rule.
5. Ask for clarification when a time range or metric has multiple unresolved meanings.

## Initial table grains

| Table | Grain | Key relationships |
|---|---|---|
| `fact_order` | One row per order | Store and order date foreign keys |
| `fact_order_line` | One row per product line in an order | Order and product foreign keys |
| `dim_store` | One row per store | Store key referenced by orders |
| `dim_product` | One row per product | Product key referenced by order lines |
| `dim_date` | One row per calendar date | Date key referenced by orders |

## Synthetic metric policies

- **GMV**: sum `fact_order.gmv_amount` for completed orders. The field is defined in this prototype as merchandise value after line discounts and before shipping and refunds. Its grain is one order. It supports store and order-date dimensions. Product-level GMV is unsupported because no line-level allocation policy is defined.
- **Order count**: count distinct completed `fact_order.order_id`; its grain is one order.
- **Units sold**: sum `fact_order_line.quantity` for lines belonging to completed orders; its grain is one order line. It supports store, product, and order-date dimensions through declared relationships.

When GMV and units sold are requested together by store and month, aggregate each measure at its native grain before combining the results. Joining order totals directly to order lines and summing the order total would multiply GMV for orders with multiple lines.

## Scope boundary

The first query vocabulary supports GMV, order count, units sold, store, product (for units sold), and calendar month. It does not model returns, taxes, shipping, promotions, customer lifetime value, or production-specific accounting policies. Add these only with explicit business definitions and data mappings.
