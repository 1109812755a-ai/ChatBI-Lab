# 模型校验与版本发布

本章演示如何把 Protégé 或文本编辑器导出的 Turtle 模型作为候选版本，先用 SHACL 检查完整性，再发布给查询运行时。文件仍是普通 Turtle；版本目录和注册表负责记录哪个版本通过校验、何时发布以及当前应使用哪个版本。

## 目录与注册表

```text
ontology/
  registry.json          # 活动版本、各版本校验报告和发布历史
  versions/
    1.0/
      retail.ttl
      semantic-model.ttl
      shapes.ttl
```

`retail.ttl` 描述零售概念和关系，`semantic-model.ttl` 保存指标及字段映射，`shapes.ttl` 规定发布时必须满足的结构约束。校验结果只能说明模型满足这些结构要求，不代表 GMV 等业务口径一定符合企业真实规则；仍需用业务问题和样例数据复核。

## 首次发布

在项目根目录运行：

```powershell
.venv\Scripts\python.exe scripts\model_registry.py bootstrap 1.0
.venv\Scripts\python.exe scripts\model_registry.py select
```

`bootstrap` 会验证仓库里已有的 `ontology/versions/1.0`，通过后将其登记为活动版本。`select` 输出查询运行时应加载的版本目录。也可以显式选择一个已发布版本：

```powershell
.venv\Scripts\python.exe scripts\model_registry.py select 1.0
```

## 注册并发布新版本

复制当前模型目录，按需编辑新版本中的 Turtle 文件，然后以新版本号注册：

```powershell
New-Item -ItemType Directory ontology\candidates -Force
Copy-Item ontology\versions\1.0 ontology\candidates\1.1 -Recurse
# 在 ontology/candidates/1.1 中编辑 retail.ttl 或 semantic-model.ttl
.venv\Scripts\python.exe scripts\model_registry.py register 1.1 --source ontology\candidates\1.1
```

注册会把候选文件复制到版本库目录。先单独检查时可以运行：

```powershell
.venv\Scripts\python.exe scripts\model_registry.py validate 1.1
```

发布命令会重新校验；校验通过后才会切换活动版本：

```powershell
.venv\Scripts\python.exe scripts\model_registry.py publish 1.1
.venv\Scripts\python.exe scripts\model_registry.py select
```

注册表 `ontology/registry.json` 保存每个候选版本的状态、校验时间、SHACL 报告，以及发布/回滚历史。候选版本即使手动校验通过，也不能在发布前被 `select` 作为运行版本使用。

## 拒绝有问题的候选版本

下面的例子复制 1.0 后，故意移除 GMV 的原生粒度定义。实际建模时不要这样修改；它只用于观察 SHACL 如何阻止不完整模型发布：

```powershell
New-Item -ItemType Directory ontology\candidates -Force
Copy-Item ontology\versions\1.0 ontology\candidates\1.2 -Recurse
# 编辑 semantic-model.ttl，删除 GMV 的 `metricGrain` 声明
.venv\Scripts\python.exe scripts\model_registry.py register 1.2 --source ontology\candidates\1.2
.venv\Scripts\python.exe scripts\model_registry.py publish 1.2
```

最后一条命令以非零状态退出，报告会指出 `Each metric must declare its native data grain.`。注册表会把 1.2 标为 `rejected` 并保留报告，活动版本保持原值。修复候选文件后，应使用新版本号重新注册，避免覆盖已经登记的候选版本。

也可只校验一个目录，不注册版本：

```powershell
.venv\Scripts\python.exe scripts\validate_model.py --model-dir ontology\versions\1.0
```

## 回滚

当新发布版本需要撤回时，选择之前发布过且校验通过的版本：

```powershell
.venv\Scripts\python.exe scripts\model_registry.py rollback 1.0
.venv\Scripts\python.exe scripts\model_registry.py select
```

回滚会保留历史记录，并将指定版本设为活动版本；它不会删除新版本或历史校验报告。

## 与查询 Agent 的关系

发布流程决定查询 Agent 可以加载哪些语义定义。在线查询应先通过 `select` 取得活动模型目录，再用 RDFLib/SPARQL 获取指标、维度和字段映射。Agent 不能绕过发布状态直接挑选任意候选文件；这样才能让每次回答都关联到一个已校验的模型版本。
