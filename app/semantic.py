"""SPARQL-backed semantic lookup and deterministic query-plan construction."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from scripts.model_registry import REGISTRY, VERSIONS

EX = Namespace("https://example.org/retail#")
OWL_CLASS = OWL.Class


class SemanticResolutionError(ValueError):
    """A requested business term is unknown, unsupported, or ambiguous."""


@dataclass
class MetricPlan:
    name: str
    label: str
    definition: str
    expression: str
    grain: str
    filters: list[str]
    source_fields: list[dict[str, str]]
    supported_dimensions: list[str]
    required_relationships: list[dict[str, str]]


@dataclass
class QueryPlan:
    model_version: str
    metrics: list[MetricPlan]
    dimensions: list[dict[str, Any]]
    time_range: dict[str, Any] | None = None
    filters: list[dict[str, str]] | None = None
    order_by: dict[str, str] | None = None
    limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["metrics"] = [asdict(metric) for metric in self.metrics]
        return result


ALIASES: dict[str, tuple[str, ...]] = {
    "gmv": ("gmv", "商品交易总额", "交易额", "销售额", "销售"),
    "ordercount": ("order count", "订单数", "订单数量"),
    "unitssold": ("units sold", "销量", "销售数量", "销售"),
    "store": ("store", "stores", "门店", "店铺"),
    "calendardate": ("date", "日期", "时间", "按天"),
    "product": ("product", "商品", "产品"),
}
FILTER_ALIASES = {
    "store_code": ("store_code", "store", "门店编码"),
    "product_name": ("product_name", "商品名称"),
    "full_date": ("full_date", "日期"),
}


def selected_model_dir(version: str | None = None) -> tuple[str, Any]:
    if not REGISTRY.is_file():
        raise SemanticResolutionError("No model registry found. Bootstrap a model version first.")
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    selected = version or registry.get("active_version")
    record = registry.get("versions", {}).get(selected)
    if not selected or not record or record.get("status") not in {"active", "published"}:
        raise SemanticResolutionError(f"Model version {selected!r} is not published.")
    if not record.get("validation", {}).get("conforms"):
        raise SemanticResolutionError(f"Model version {selected!r} has no successful SHACL validation.")
    path = VERSIONS / selected
    if not path.is_dir():
        raise SemanticResolutionError(f"Published model files are missing for version {selected!r}.")
    return selected, path


def load_graph(version: str | None = None) -> tuple[str, Graph]:
    selected, model_dir = selected_model_dir(version)
    graph = Graph()
    for file_name in ("retail.ttl", "semantic-model.ttl"):
        graph.parse(model_dir / file_name, format="turtle")
    return selected, graph


def _canonical(value: str, allowed: Iterable[str], *, kind: str) -> str:
    text = value.strip().casefold()
    hits = [name for name in allowed if text in ALIASES.get(name.casefold(), ()) or text == name.casefold()]
    if len(hits) > 1:
        raise SemanticResolutionError(f"“{value}”可能指{'、'.join(hits)}，请明确指定。")
    if not hits:
        raise SemanticResolutionError(f"暂不支持{kind}“{value}”。当前支持：{'、'.join(allowed)}。")
    return hits[0]


def _strings(graph: Graph, subject: URIRef, predicate: URIRef) -> list[str]:
    return sorted(str(value) for value in graph.objects(subject, predicate))


def metric_catalog(version: str | None = None) -> list[dict[str, Any]]:
    _selected, graph = load_graph(version)
    query = """
        PREFIX : <https://example.org/retail#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?metric ?label ?definition ?expression ?grain WHERE {
          ?metric a :Metric ; rdfs:label ?label ; :metricDefinition ?definition ;
                  :metricExpression ?expression ; :metricGrain ?grain .
        }
        ORDER BY ?metric ?label
    """
    rows: dict[str, dict[str, Any]] = {}
    for row in graph.query(query):
        key = str(row.metric)
        item = rows.setdefault(key, {"iri": key, "labels": [], "definition": str(row.definition),
                                     "expression": str(row.expression), "grain": str(row.grain)})
        item["labels"].append(str(row.label))
    return list(rows.values())


def _resolve_metric(graph: Graph, term: str) -> URIRef:
    known = [str(subject).rsplit("#", 1)[-1] for subject in graph.subjects(RDF.type, EX.Metric)]
    return EX[_canonical(term, known, kind="指标")]


def _resolve_dimension(graph: Graph, term: str) -> URIRef:
    known = [str(subject).rsplit("#", 1)[-1] for subject in graph.subjects(RDF.type, OWL_CLASS)]
    known = [name for name in known if name in {"Store", "Product", "CalendarDate"}]
    return EX[_canonical(term, known, kind="维度")]


def _metric_plan(graph: Graph, metric: URIRef) -> MetricPlan:
    label_nodes = list(graph.objects(metric, RDFS.label))
    labels = sorted((str(value) for value in label_nodes), key=lambda value: (value.lower(), value))
    field_query = """
        PREFIX : <https://example.org/retail#>
        SELECT ?table ?column WHERE {
          ?metric :metricUsesField ?field . ?field :fieldTable ?table ; :fieldName ?column .
        } ORDER BY ?table ?column
    """
    source_fields = [{"table": str(row.table), "column": str(row.column)}
                     for row in graph.query(field_query, initBindings={"metric": metric})]
    dimensions = sorted(str(value).rsplit("#", 1)[-1]
                        for value in graph.objects(metric, EX.metricSupportedDimension))
    relationships = []
    for relation in graph.objects(metric, EX.metricRequiresRelationship):
        joins = _strings(graph, relation, EX.joinCondition)
        relationships.append({"name": str(relation).rsplit("#", 1)[-1],
                              "join_condition": joins[0] if joins else ""})
    label = next((str(value) for value in label_nodes if getattr(value, "language", None) == "zh"),
                 labels[0] if labels else str(metric))
    return MetricPlan(
        name=str(metric).rsplit("#", 1)[-1], label=label,
        definition=_strings(graph, metric, EX.metricDefinition)[0],
        expression=_strings(graph, metric, EX.metricExpression)[0],
        grain=_strings(graph, metric, EX.metricGrain)[0],
        filters=_strings(graph, metric, EX.metricFilter), source_fields=source_fields,
        supported_dimensions=dimensions, required_relationships=relationships)


def _dimension_mapping(graph: Graph, dimension: URIRef) -> dict[str, Any]:
    table_query = """
        PREFIX : <https://example.org/retail#>
        SELECT ?table ?key WHERE { ?dimension :sourceTable ?table ; :sourcePrimaryKey ?key . }
    """
    rows = list(graph.query(table_query, initBindings={"dimension": dimension}))
    if not rows:
        raise SemanticResolutionError(f"维度 {dimension} 没有物理表映射。")
    column_query = """
        PREFIX : <https://example.org/retail#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?column WHERE {
          ?property a owl:DatatypeProperty ; rdfs:domain ?dimension ; :sourceColumn ?column .
        } ORDER BY ?column
    """
    cols = list(graph.query(column_query, initBindings={"dimension": dimension}))
    relationship_query = """
        PREFIX : <https://example.org/retail#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?relationship ?join WHERE {
          ?relationship a owl:ObjectProperty ; :joinCondition ?join .
          { ?relationship rdfs:range ?dimension . }
          UNION
          { ?relationship rdfs:domain ?dimension . }
        } ORDER BY ?relationship
    """
    relationships = [{"name": str(row.relationship).rsplit("#", 1)[-1],
                      "join_condition": str(row.join)}
                     for row in graph.query(relationship_query, initBindings={"dimension": dimension})]
    labels = [str(value) for value in graph.objects(dimension, RDFS.label)]
    label = next((value for value in labels if any(ord(char) > 127 for char in value)),
                 str(dimension).rsplit("#", 1)[-1])
    return {"name": str(dimension).rsplit("#", 1)[-1], "label": label,
            "table": str(rows[0].table), "key": str(rows[0].key),
            "columns": [str(row.column) for row in cols], "relationships": relationships}


def _filter_mapping(graph: Graph, field: str) -> tuple[str, str]:
    text = field.strip().casefold()
    query = """
        PREFIX : <https://example.org/retail#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?dimension ?column ?local WHERE {
          ?property :sourceColumn ?column ; rdfs:domain ?dimension .
          BIND(STR(?property) AS ?propertyIri)
          BIND(REPLACE(STR(?property), "^.*#", "") AS ?local)
        }
    """
    matches = []
    for row in graph.query(query):
        local = str(row.local).casefold()
        basename = str(row.column).rsplit(".", 1)[-1].casefold()
        aliases = FILTER_ALIASES.get(basename, (basename, local))
        if text == local or text == basename or text in aliases:
            matches.append((str(row.dimension).rsplit("#", 1)[-1], str(row.column)))
    matches = sorted(set(matches))
    if len(matches) > 1:
        raise SemanticResolutionError(f"过滤字段“{field}”对应多个数据字段，请明确指定。")
    if not matches:
        raise SemanticResolutionError(f"暂不支持过滤字段“{field}”。")
    return matches[0]


def build_query_plan(metrics: str | list[str], dimensions: list[str], *,
                     time_range: dict[str, str] | None = None,
                     filters: list[dict[str, str]] | None = None,
                     order_by: dict[str, str] | None = None,
                     limit: int | None = None,
                     version: str | None = None) -> QueryPlan:
    selected, graph = load_graph(version)
    terms = [metrics] if isinstance(metrics, str) else metrics
    metric_ids = [_resolve_metric(graph, term) for term in terms]
    dimension_ids = [_resolve_dimension(graph, term) for term in dimensions]
    plans = [_metric_plan(graph, metric) for metric in metric_ids]
    for plan in plans:
        unsupported = [str(item).rsplit("#", 1)[-1] for item in dimension_ids
                       if str(item).rsplit("#", 1)[-1] not in plan.supported_dimensions]
        if unsupported:
            raise SemanticResolutionError(f"指标“{plan.label}”不支持维度：{'、'.join(unsupported)}。")
    normalized_order_by = None
    if order_by is not None:
        if not isinstance(order_by, dict) or set(order_by) != {"metric", "direction"}:
            raise SemanticResolutionError("排序条件必须包含 metric 和 direction 两项。")
        if not dimension_ids:
            raise SemanticResolutionError("指标排序只适用于按维度分组的查询。")
        order_metric = _resolve_metric(graph, str(order_by["metric"]))
        order_metric_name = str(order_metric).rsplit("#", 1)[-1]
        if order_metric_name not in {plan.name for plan in plans}:
            raise SemanticResolutionError("排序指标必须是本次查询的指标之一。")
        direction = order_by["direction"]
        if not isinstance(direction, str) or direction.casefold() not in {"asc", "desc"}:
            raise SemanticResolutionError("排序方向只支持 asc 或 desc。")
        normalized_order_by = {"metric": order_metric_name, "direction": direction.casefold()}
    if limit is not None and (type(limit) is not int or limit < 1 or limit > 500):
        raise SemanticResolutionError("结果条数必须是 1 到 500 之间的整数。")
    mapped_filters = []
    for item in filters or []:
        if set(item) != {"field", "value"}:
            raise SemanticResolutionError("过滤条件只接受 field 和 value 两项。")
        dimension, column = _filter_mapping(graph, item["field"])
        if any(dimension not in plan.supported_dimensions for plan in plans):
            raise SemanticResolutionError(f"请求的指标不支持按 {dimension} 过滤。")
        mapped_filters.append({"column": column, "operator": "=", "value": item["value"]})
    resolved_time_range = None
    if time_range:
        resolved_time_range = {
            **time_range,
            "dimension_mapping": _dimension_mapping(graph, EX.CalendarDate),
        }
    return QueryPlan(selected, plans, [_dimension_mapping(graph, item) for item in dimension_ids],
                     resolved_time_range, mapped_filters, normalized_order_by, limit)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", action="append", required=True)
    parser.add_argument("--dimension", action="append", default=[])
    parser.add_argument("--version")
    args = parser.parse_args()
    try:
        plan = build_query_plan(args.metric, args.dimension, version=args.version)
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    except SemanticResolutionError as error:
        print(str(error))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
