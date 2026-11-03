# 用 SPARQL 查询语义，用 SHACL 校验结构

RDFLib 把已发布的 Turtle 文件加载成 RDF 图。SPARQL 从图中查询业务语义，例如某个指标的定义、粒度、过滤和物理字段映射；SHACL 则检查图是否满足必需的结构约束。查询回答“模型里写了什么”，校验回答“模型是否满足发布要求”。

## 运行项目中的 SPARQL 示例

```powershell
.venv\Scripts\python.exe scripts\run_sparql_examples.py
.venv\Scripts\python.exe -m app.semantic --metric GMV --metric UnitsSold --dimension Store --dimension CalendarDate
```

第一个命令运行本章列出的两条 SPARQL，读取当前活动版本并展示指标到来源字段的映射。第二个命令由语义服务构建结构化计划；计划包含指标定义、原生粒度、过滤条件、字段、维度表与 Join 映射以及模型版本。

## 查询指标定义和粒度

```sparql
PREFIX : <https://example.org/retail#>
SELECT ?metric ?definition ?grain WHERE {
  ?metric a :Metric ; :metricDefinition ?definition ; :metricGrain ?grain .
}
ORDER BY ?metric
```

该查询在版本 1.0 中返回 GMV、订单数和销量三项指标。定义和粒度是 Turtle 中的 RDF 字面值；指标本身是 `:Metric` 类的实例。

## 查询指标到物理字段的映射

```sparql
PREFIX : <https://example.org/retail#>
SELECT ?metric ?table ?column WHERE {
  ?metric a :Metric ; :metricUsesField ?field .
  ?field :fieldTable ?table ; :fieldName ?column .
}
ORDER BY ?metric ?table ?column
```

它把业务指标连到 `fact_order.gmv_amount`、`fact_order.status`、`fact_order.order_id` 和 `fact_order_line.quantity` 等物理字段。SQL 运行时只应使用已映射字段；SPARQL 返回映射本身，不会读取或聚合零售事实记录。

## 结构校验和失败报告

```powershell
.venv\Scripts\python.exe scripts\validate_model.py --model-dir ontology\versions\1.0
.venv\Scripts\python.exe scripts\model_registry.py validate 1.0
```

第一条命令直接报告某个目录是否符合 `shapes.ttl`；第二条命令还会把校验时间、状态和报告写入 `ontology/registry.json`。例如，若某个指标缺少 `:metricGrain`，SHACL 会报告“Each metric must declare its native data grain.”。发布候选模型会再次执行相同校验，失败时不会切换活动版本。完整发布流程见[模型校验与版本发布](03-validation-and-versioning.md)。

## 在 Python 中执行 SPARQL

```python
from app.semantic import load_graph

version, graph = load_graph()  # 默认读取注册表里的活动发布版本
rows = graph.query("""
    PREFIX : <https://example.org/retail#>
    SELECT ?field ?table ?column WHERE {
      :GMV :metricUsesField ?field .
      ?field :fieldTable ?table ; :fieldName ?column .
    }
""")
for row in rows:
    print(version, row.table, row.column)
```

固定一个版本用于复现历史查询时，可调用 `load_graph("1.0")`；只有成功校验且曾经发布的版本才可被选取。
