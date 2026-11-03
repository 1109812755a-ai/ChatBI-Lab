# 2. RDF、OWL 与 Turtle

本章回答一个常见问题：RDF 和 OWL 是两种并列的格式吗？不是。**RDF 提供图和三元组的数据模型；OWL 是用 RDF 图表达的本体语言，用来给类、属性和关系赋予更精确的形式语义。Turtle 是书写 RDF 图的一种文本语法。**

本章对应项目文件：

- [零售本体 `retail.ttl`](../../ontology/versions/1.0/retail.ttl)
- [指标语义 `semantic-model.ttl`](../../ontology/versions/1.0/semantic-model.ttl)
- [SHACL 约束 `shapes.ttl`](../../ontology/versions/1.0/shapes.ttl)

## RDF：用三元组表达陈述

RDF 的基本单位是三元组：

```text
主语 -- 谓语/关系 --> 宾语
```

例如“门店 A 有订单 123”可以写成：

```turtle
:storeA a :Store ;
    :hasOrder :order123 .

:order123 a :Order .
```

这里 `:storeA`、`:hasOrder`、`:order123` 组成一条关系陈述。RDF 图就是很多这样的陈述连在一起。[W3C RDF Primer](https://www.w3.org/TR/rdf-primer/) 对 RDF 的介绍也以 subject-predicate-object 三元组为基本结构。

## OWL：给概念和关系正式含义

项目本体中有：

```turtle
:Order a owl:Class .
:Store a owl:Class .

:hasOrder a owl:ObjectProperty ;
    rdfs:domain :Store ;
    rdfs:range :Order .
```

第一行表面上仍是一个 RDF 三元组：主语 `:Order`、谓语 `rdf:type`（Turtle 中写作 `a`）、宾语 `owl:Class`。由于它使用 OWL 词汇，这条 RDF 陈述同时声明 `:Order` 是一个 OWL 类。`owl:ObjectProperty` 则声明 `:hasOrder` 是连接资源的对象属性。OWL 2 是用于表达本体的语言，本体主要通过 RDF 文档交换；[W3C OWL 2 Primer](https://www.w3.org/TR/owl-primer/) 介绍了这些结构和含义。

所以两者关系不是“RDF 文件加一个独立 OWL 文件”，而是：**OWL 本体中的声明也编码成 RDF 图中的三元组。**并非任意 RDF 图都是有完整 OWL 语义的本体；OWL 词汇和 OWL 语义约束规定了哪些声明代表类、属性、公理等。

## Turtle：让 RDF 图更好读

Turtle 是 RDF 的一种文本序列化语法。比如：

```turtle
:storeA a :Store ;
    :hasOrder :order123 .
```

分号表示同一个主语继续有另一条谓语；句点结束这个主语的一组陈述。`a` 是 `rdf:type` 的简写。Turtle 只是把 RDF 图写到文本文件的方法；同一张图也可以用 RDF/XML、JSON-LD 等语法表示。

在项目的 [零售本体文件](../../ontology/versions/1.0/retail.ttl) 中，`retail.ttl` 以 Turtle 保存 OWL 类、属性和数据源注记。真实订单行仍保存在 SQLite 表里，不会把大量交易行重复放进本体文件。

## 把业务关系映射到表

本体里 `:hasOrder` 表示门店和订单的业务关系；相同关系还附带了物理 Join 条件：

```turtle
:hasOrder a owl:ObjectProperty ;
    rdfs:domain :Store ;
    rdfs:range :Order ;
    :joinCondition "dim_store.store_key = fact_order.store_key" .
```

这让 Agent 能把“门店有订单”从业务关系映射到数据库连接条件。表粒度仍须与指标口径一起检查：`fact_order` 一行一个订单，`fact_order_line` 一行一个商品明细。仅有正确 Join 条件并不能保证聚合正确。

## 需要区分 OWL 语义和数据校验

OWL 主要表达概念语义和逻辑关系。比如 `rdfs:domain` 和 `rdfs:range` 提供类型含义；它们不是数据库外键或“缺少字段就拒绝发布”的校验器。OWL 通常采用开放世界假设：数据没有写出一个关系，不等于断定这个关系不存在。

本项目用 SHACL 做操作性的完整性检查，例如每个指标必须有粒度和来源字段。SHACL 规则在 [shapes.ttl](../../ontology/versions/1.0/shapes.ttl)，指标在 [semantic-model.ttl](../../ontology/versions/1.0/semantic-model.ttl)。后续章节会展示如何运行 SPARQL 查询语义图、如何运行 SHACL 校验。
