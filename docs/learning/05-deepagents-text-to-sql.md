# DeepAgents、语义规划与安全 SQL

本章把自然语言问数分成两部分：DeepAgents 识别用户想问什么、决定调用哪个工具；项目自己的工具查询已发布本体，生成固定结构的语义计划，再把计划编译为只读 SQL。模型不会直接提交可执行 SQL。

## 配置并运行 DeepAgents

先安装依赖并建立本地数据与模型版本：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\init_db.py
.venv\Scripts\python.exe scripts\model_registry.py bootstrap 1.0
Copy-Item .env.example .env
```

在 `.env` 中填入所选模型服务的密钥，并按需修改 `DEEPAGENTS_MODEL` 或 `OPENAI_BASE_URL`。运行：

```powershell
.venv\Scripts\python.exe -m app.agent "按门店看上个月 GMV 和销量"
```

问答 Agent 使用 `deepagents.create_deep_agent`，从应用设置读取显式模型。它只接收项目注册的语义解析、查询和指标目录工具；不提供写文件、Shell 或子 Agent 委派能力。没有配置模型凭据时，可运行同一项目的固定问题演示，检查本体到 SQL 的确定性路径：

```powershell
.venv\Scripts\python.exe -m app.demo --as-of 2026-11-02 "按门店看上个月 GMV 和销量"
```

## 每一层分别负责什么

```text
自然语言问题
    │ DeepAgents：理解意图、决定工具调用、组织回答
    ▼
query_retail_data(metrics, dimensions, time range, filters)
    │ 项目工具：拒绝未知或歧义术语
    ▼
RDFLib + SPARQL：读取活动版本中的口径、粒度、字段、Join 映射
    │ 项目服务：生成带版本号的结构化语义计划
    ▼
SQL 编译器：只使用已知指标表达式、映射表列和固定 Join 模板
    │ SQL 执行器：参数化过滤、只读连接、行数上限
    ▼
结果 + 指标定义 + 过滤条件 + 模型版本
```

DeepAgents 是编排框架：负责模型调用、工具选择和多步消息流。`app/semantic.py`、`app/sql.py` 和 `app/agent.py` 中的工具是项目负责的领域实现：本体检索、口径约束、SQL 安全和结果来源都由这些代码决定。更换 Agent harness 时，这些领域服务可以继续使用。

## 结构化语义计划

Agent 将问题转换为工具参数，例如：

```json
{
  "metrics": ["GMV", "UnitsSold"],
  "dimensions": ["Store"],
  "time_period": "previous_month"
}
```

工具按活动模型版本解析这些概念，并返回指标解释、粒度、数据库字段、维度表、Join 映射和日期区间。日期区间采用左闭右开形式；在参考日期 2026-11-02 下，“上个月”对应 `[2026-10-01, 2026-11-01)`。

可单独检查计划，不调用语言模型：

```powershell
.venv\Scripts\python.exe -m app.semantic --metric GMV --metric UnitsSold --dimension Store
```

## 为什么不让模型自由生成 SQL

即使 SQL 语法正确，跨订单和订单明细直接求和也可能重复计算订单级 GMV。项目按指标原生粒度分别聚合，再按所选维度组合结果。SQL 编译器使用有限指标表达式和固定 Join 模板；用户过滤值作为 `?` 参数传给 SQLite，不拼进 SQL 文本。

执行器还检查物理表和字段 allowlist，限制为最多 500 行，并通过 SQLite 只读模式、`query_only` 和 authorizer 拒绝写操作。语义计划中的表达式、表名或字段名若与当前模型不一致，会被重新解析或拒绝。

## 可观察的答案依据

工具结果包含执行行、最终 SQL、绑定参数、指标定义、过滤条件和模型版本。例如本地演示的 GMV 和销量都关联模型版本 1.0。用户追问“GMV 如何计算”时，回答应引用工具返回的定义，而不是让模型临时编造指标口径。

如需学习 SQL 安全和结果检查，可查看 `app/sql.py`、`app/semantic.py` 与 `data/expected-results.json`。评估和 Bad Case 的记录方法见下一章。
