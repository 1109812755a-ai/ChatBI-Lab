"""Compile published semantic plans into bounded, parameterized read-only SQL."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from app.semantic import QueryPlan, SemanticResolutionError, build_query_plan
from app.progress import emit_progress

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "retail.sqlite"
MAX_ROWS = 500

METRIC_SQL = {
    "GMV": ("fact_order", "SUM(o.gmv_amount)"),
    "OrderCount": ("fact_order", "COUNT(DISTINCT o.order_id)"),
    "UnitsSold": ("fact_order_line", "SUM(ol.quantity)"),
}
ALLOWED_TABLES = {"fact_order", "fact_order_line", "dim_store", "dim_date", "dim_product"}
ALLOWED_COLUMNS = {
    "fact_order": {"order_id", "store_key", "order_date_key", "gmv_amount", "status"},
    "fact_order_line": {"order_line_id", "order_id", "product_key", "quantity", "unit_price", "discount_amount"},
    "dim_store": {"store_key", "store_code", "store_name"},
    "dim_date": {"date_key", "full_date", "year", "month", "day"},
    "dim_product": {"product_key", "product_code", "product_name", "category"},
}


class UnsafeQueryError(ValueError):
    """Raised when a query cannot be proven read-only and schema-mapped."""


def _validate_plan(plan: QueryPlan) -> None:
    if not plan.metrics:
        raise SemanticResolutionError("至少需要一个指标。")
    if len(plan.metrics) > 3:
        raise SemanticResolutionError("单次查询最多支持三个指标。")
    if plan.limit is not None and (type(plan.limit) is not int or plan.limit < 1 or plan.limit > MAX_ROWS):
        raise SemanticResolutionError(f"结果条数必须是 1 到 {MAX_ROWS} 之间的整数。")
    if plan.order_by is not None:
        if not isinstance(plan.order_by, dict) or set(plan.order_by) != {"metric", "direction"}:
            raise SemanticResolutionError("排序条件必须包含 metric 和 direction 两项。")
        order_metric = plan.order_by["metric"]
        direction = plan.order_by["direction"]
        if not isinstance(order_metric, str) or not any(metric.name == order_metric for metric in plan.metrics):
            raise SemanticResolutionError("排序指标必须是本次查询的指标之一。")
        if not isinstance(direction, str) or direction not in {"asc", "desc"}:
            raise SemanticResolutionError("排序方向只支持 asc 或 desc。")
        if not plan.dimensions:
            raise SemanticResolutionError("指标排序只适用于按维度分组的查询。")
    for metric in plan.metrics:
        if metric.name not in METRIC_SQL:
            raise SemanticResolutionError(f"未知指标映射：{metric.name}")
        for field in metric.source_fields:
            table, column = field["table"], field["column"]
            if table not in ALLOWED_TABLES or column not in ALLOWED_COLUMNS.get(table, set()):
                raise UnsafeQueryError(f"来源字段未加入 SQL allowlist：{table}.{column}")
    for dimension in plan.dimensions:
        table = dimension["table"]
        if table not in ALLOWED_TABLES:
            raise UnsafeQueryError(f"维度表未加入 SQL allowlist：{table}")
        for column in dimension.get("columns", []):
            source_table, source_column = column.split(".", 1)
            if source_table not in ALLOWED_TABLES or source_column not in ALLOWED_COLUMNS.get(source_table, set()):
                raise UnsafeQueryError(f"维度字段未加入 SQL allowlist：{column}")
    available_relationships = {
        relation["name"]
        for metric in plan.metrics for relation in metric.required_relationships
    }
    available_relationships.update(
        relation["name"]
        for dimension in plan.dimensions for relation in dimension.get("relationships", [])
    )
    if plan.time_range:
        time_mapping = plan.time_range.get("dimension_mapping")
        if not time_mapping or time_mapping.get("table") != "dim_date" \
                or "orderedOn" not in {item["name"] for item in time_mapping.get("relationships", [])}:
            raise UnsafeQueryError("Time filtering requires a published CalendarDate-to-Order relationship.")
        available_relationships.update(item["name"] for item in time_mapping.get("relationships", []))
    required_relationships = {"Store": "hasOrder", "CalendarDate": "orderedOn", "Product": "refersToProduct"}
    for dimension in plan.dimensions:
        relationship = required_relationships[dimension["name"]]
        if relationship not in available_relationships:
            raise UnsafeQueryError(f"Join for {dimension['name']} is not declared in the published ontology.")
    if any(metric.name == "UnitsSold" for metric in plan.metrics) and "containsLine" not in available_relationships:
        raise UnsafeQueryError("UnitsSold requires the published Order-to-OrderLine relationship.")
    for condition in plan.filters or []:
        if condition.get("column") == "dim_store.store_code" and "hasOrder" not in available_relationships:
            raise UnsafeQueryError("Store filtering requires the published Store-to-Order relationship.")
        if condition.get("column") == "dim_product.product_name" and "refersToProduct" not in available_relationships:
            raise UnsafeQueryError("Product filtering requires the published OrderLine-to-Product relationship.")


def compile_plan(plan: QueryPlan, *, row_limit: int = MAX_ROWS) -> tuple[str, list[Any]]:
    """Compile a canonical RDF-resolved plan; never accept model-authored SQL."""
    _validate_plan(plan)
    safety_limit = max(1, min(int(row_limit), MAX_ROWS))
    limit = min(plan.limit if plan.limit is not None else safety_limit, safety_limit)
    dimension_names = [item["name"] for item in plan.dimensions]
    dimension_specs = {
        "Store": ("dim_store", "store_key", "store_code", "ds"),
        "CalendarDate": ("dim_date", "date_key", "full_date", "dd"),
        "Product": ("dim_product", "product_key", "product_name", "dp"),
    }
    if any(name not in dimension_specs for name in dimension_names):
        raise UnsafeQueryError("query plan contains an unsupported dimension mapping")

    ctes: list[str] = []
    parameters: list[Any] = []
    group_aliases = [f"k{index}" for index in range(len(dimension_names))]
    for index, metric in enumerate(plan.metrics):
        base_table, expression = METRIC_SQL[metric.name]
        order_grain = base_table == "fact_order"
        from_sql = "fact_order o" if order_grain else (
            "fact_order_line ol JOIN fact_order o ON o.order_id = ol.order_id"
        )
        joins: list[str] = []
        joined: set[str] = set()
        for dim_name in dimension_names:
            table, key, _label, alias = dimension_specs[dim_name]
            if dim_name == "Store":
                joins.append(f"JOIN {table} {alias} ON {alias}.{key} = o.store_key")
                joined.add(dim_name)
            elif dim_name == "CalendarDate":
                joins.append(f"JOIN {table} {alias} ON {alias}.{key} = o.order_date_key")
                joined.add(dim_name)
            elif dim_name == "Product":
                if order_grain:
                    raise SemanticResolutionError(f"指标“{metric.label}”不支持商品维度。")
                joins.append(f"JOIN {table} {alias} ON {alias}.{key} = ol.product_key")
                joined.add(dim_name)

        where = ["o.status = ?"]
        parameters.append("completed")
        # Parameterized values are only applied through known mapped dimensions.
        for condition in plan.filters or []:
            column = condition.get("column")
            operator = condition.get("operator")
            value = condition.get("value")
            if not isinstance(value, str) or operator != "=":
                raise UnsafeQueryError("Only string equality filters are supported.")
            if column == "dim_store.store_code":
                if "Store" not in joined:
                    joins.append("JOIN dim_store ds ON ds.store_key = o.store_key")
                    joined.add("Store")
                where.append("ds.store_code = ?")
                parameters.append(value)
            elif column == "dim_product.product_name" and not order_grain:
                if "Product" not in joined:
                    joins.append("JOIN dim_product dp ON dp.product_key = ol.product_key")
                    joined.add("Product")
                where.append("dp.product_name = ?")
                parameters.append(value)
            else:
                raise UnsafeQueryError(f"Filter field is not supported for {metric.name}: {column}")

        if plan.time_range:
            start, end = plan.time_range.get("start"), plan.time_range.get("end")
            try:
                parsed_start, parsed_end = date.fromisoformat(start or ""), date.fromisoformat(end or "")
            except ValueError as error:
                raise SemanticResolutionError("日期范围必须使用 YYYY-MM-DD 格式。") from error
            if parsed_start >= parsed_end:
                raise SemanticResolutionError("日期范围必须是有效的半开区间 [start, end)。")
            if "CalendarDate" not in joined:
                joins.append("JOIN dim_date dd ON dd.date_key = o.order_date_key")
                joined.add("CalendarDate")
            where.extend(["dd.full_date >= ?", "dd.full_date < ?"])
            parameters.extend([start, end])

        select_keys = []
        for key_index, dim_name in enumerate(dimension_names):
            table, key, _label, alias = dimension_specs[dim_name]
            select_keys.append(f"{alias}.{key} AS {group_aliases[key_index]}")
        select_keys.append(f"{expression} AS v{index}")
        group_by = ", ".join(
            f"{dimension_specs[name][3]}.{dimension_specs[name][1]}" for name in dimension_names
        )
        sql = f"SELECT {', '.join(select_keys)} FROM {from_sql} {' '.join(joins)} WHERE {' AND '.join(where)}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        ctes.append(f"m{index} AS ({sql})")

    if dimension_names:
        keys = ", ".join(group_aliases)
        key_union = " UNION ".join(f"SELECT {keys} FROM m{index}" for index in range(len(ctes)))
        ctes.append(f"groups AS ({key_union})")
        select_parts = []
        from_parts = ["groups g"]
        for key_index, dim_name in enumerate(dimension_names):
            table, key, label_column, alias = dimension_specs[dim_name]
            select_parts.append(f"{alias}.{label_column} AS {dim_name}")
            from_parts.append(f"JOIN {table} {alias} ON {alias}.{key} = g.k{key_index}")
        for index, metric in enumerate(plan.metrics):
            join_conditions = " AND ".join(f"m{index}.k{k} = g.k{k}" for k in range(len(dimension_names)))
            from_parts.append(f"LEFT JOIN m{index} ON {join_conditions}")
            select_parts.append(f"m{index}.v{index} AS {metric.name}")
        final = f"SELECT {', '.join(select_parts)} FROM {' '.join(from_parts)}"
        order_terms = []
        if plan.order_by:
            direction = {"asc": "ASC", "desc": "DESC"}[plan.order_by["direction"]]
            order_terms.append(f"{plan.order_by['metric']} {direction}")
        order_terms.extend(f"{dimension_specs[name][3]}.{dimension_specs[name][2]} ASC"
                           for name in dimension_names)
        # Keys disambiguate duplicate display labels and make ties deterministic.
        order_terms.extend(f"{dimension_specs[name][3]}.{dimension_specs[name][1]} ASC"
                           for name in dimension_names)
        final += " ORDER BY " + ", ".join(order_terms)
    else:
        select_parts = [f"m{index}.v{index} AS {metric.name}" for index, metric in enumerate(plan.metrics)]
        final = f"SELECT {', '.join(select_parts)} FROM " + " CROSS JOIN ".join(f"m{index}" for index in range(len(ctes)))
    sql = "WITH " + ", ".join(ctes) + f" {final} LIMIT ?"
    parameters.append(limit)
    emit_progress("sql_validation", "started", "正在校验 SQL 的只读权限和表字段范围")
    validate_readonly_query(sql)
    emit_progress("sql_validation", "completed", "SQL 只读和表字段校验通过")
    return sql, parameters


def validate_readonly_query(sql: str) -> None:
    """Reject multiple statements and non-read queries before SQLite authorizer checks."""
    normalized = sql.strip()
    if not re.match(r"^(WITH|SELECT)\b", normalized, re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT queries are permitted.")
    if ";" in normalized.rstrip(";"):
        raise UnsafeQueryError("Multiple SQL statements are not permitted.")
    denied = re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|REPLACE)\b", normalized, re.IGNORECASE)
    if denied:
        raise UnsafeQueryError(f"Disallowed SQL operation: {denied.group(1).upper()}")
    table_refs = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", normalized, re.IGNORECASE)
    unknown = set(table_refs) - ALLOWED_TABLES - {f"m{i}" for i in range(10)} - {"groups"}
    if unknown:
        raise UnsafeQueryError(f"SQL references tables outside the allowlist: {sorted(unknown)}")


def _authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    return sqlite3.SQLITE_OK if action in allowed_actions else sqlite3.SQLITE_DENY


def execute_plan(plan: QueryPlan, *, database: Path = DATABASE, row_limit: int = MAX_ROWS) -> dict[str, Any]:
    emit_progress("sql_compilation", "started", "正在根据语义计划生成 SQL")
    try:
        sql, parameters = compile_plan(plan, row_limit=row_limit)
    except Exception:
        emit_progress("sql_compilation", "failed", "SQL 生成或校验失败")
        raise
    emit_progress("sql_compilation", "completed", "SQL 已生成并通过校验")
    safety_limit = max(1, min(int(row_limit), MAX_ROWS))
    effective_limit = min(plan.limit if plan.limit is not None else safety_limit, safety_limit)
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    emit_progress("database_execution", "started", "正在执行只读数据查询")
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(lambda: 1, 2_000_000)
        cursor = connection.execute(sql, parameters)
        columns = [description[0] for description in cursor.description or []]
        rows = [dict(row) for row in cursor.fetchmany(max(1, effective_limit))]
        emit_progress("database_execution", "completed", "数据查询完成", row_count=len(rows))
        return {"columns": columns, "rows": rows, "row_count": len(rows), "sql": sql,
                "parameters": parameters, "truncated": len(rows) >= effective_limit}
    except sqlite3.DatabaseError as error:
        emit_progress("database_execution", "failed", "只读数据查询执行失败")
        raise UnsafeQueryError(f"Read-only query failed validation or execution: {error}") from error
    finally:
        if connection is not None:
            connection.close()


def execute_plan_dict(plan_dict: dict[str, Any], *, row_limit: int = MAX_ROWS) -> dict[str, Any]:
    """Re-resolve client/LLM supplied plan identifiers against the active model."""
    try:
        metrics = [item["name"] for item in plan_dict["metrics"]]
        dimensions = [item["name"] for item in plan_dict["dimensions"]]
        filters = []
        for condition in plan_dict.get("filters") or []:
            column = condition.get("column", "")
            basename = column.rsplit(".", 1)[-1]
            filter_alias = {"store_code": "store_code", "product_name": "product_name"}.get(basename)
            if not filter_alias or condition.get("operator") != "=":
                raise UnsafeQueryError(f"Unmapped filter in query plan: {column}")
            filters.append({"field": filter_alias, "value": condition.get("value", "")})
        plan = build_query_plan(metrics, dimensions, time_range=plan_dict.get("time_range"),
                                filters=filters, order_by=plan_dict.get("order_by"),
                                limit=plan_dict.get("limit"), version=plan_dict.get("model_version"))
    except (KeyError, TypeError) as error:
        raise SemanticResolutionError(f"Malformed semantic plan: {error}") from error
    result = execute_plan(plan, row_limit=row_limit)
    return {**result, "model_version": plan.model_version,
            "metrics": [{"name": metric.name, "label": metric.label,
                         "definition": metric.definition,
                         "grain": metric.grain, "filters": metric.filters}
                        for metric in plan.metrics],
            "dimensions": [dimension["name"] for dimension in plan.dimensions],
            "time_range": plan.time_range, "semantic_filters": plan.filters,
            "semantic_plan": plan.to_dict()}
