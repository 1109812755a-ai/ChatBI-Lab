"""Callable golden-set evaluation service shared by the CLI and Streamlit UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent import query_retail_data
from app.bad_cases import record_bad_case
from app.sql import UnsafeQueryError, validate_readonly_query
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "cases.json"
SUMMARY_PATH = ROOT / "data" / "evaluation" / "latest-summary.json"
REGISTRY_PATH = ROOT / "ontology" / "registry.json"


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    try:
        result = query_retail_data.invoke(case["intent"])
    except ValidationError as error:
        result = {"status": "clarification_required", "message": str(error)}
    expected_status = case["expected_status"]
    status_ok = result.get("status") == expected_status
    sql_valid: bool | None = None
    rows_ok: bool | None = None
    metrics_ok: bool | None = None
    dimensions_ok: bool | None = None
    if result.get("status") == "answered":
        try:
            validate_readonly_query(result["sql"])
            sql_valid = True
        except (UnsafeQueryError, KeyError):
            sql_valid = False
        expected_rows = case.get("expected_rows", [])
        actual_rows = result.get("rows", [])
        key = lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True)
        rows_ok = (actual_rows == expected_rows if case.get("assert_order") else
                   sorted(actual_rows, key=key) == sorted(expected_rows, key=key))
        metrics_ok = [item["name"] for item in result.get("metrics", [])] == case.get("expected_metrics")
        dimensions_ok = result.get("dimensions") == case.get("expected_dimensions")
    correction_ok = status_ok and (
        expected_status != "clarification_required" or not result.get("sql")
    )
    is_unsupported_case = case.get("failure_category") in {
        "unsupported_dimension", "ambiguous_metric", "unknown_metric"
    }
    success = status_ok and correction_ok and (sql_valid is not False) and (rows_ok is not False) \
        and (metrics_ok is not False) and (dimensions_ok is not False)
    return {
        "id": case["id"], "question": case["question"],
        "semantic_resolution": "pass" if status_ok else "fail",
        "sql_valid": "pass" if sql_valid else ("fail" if sql_valid is False else "not_applicable"),
        "result_correct": "pass" if rows_ok else ("fail" if rows_ok is False else "not_applicable"),
        "clarification_behavior": "pass" if correction_ok else "fail",
        "unsupported_query_handling": ("pass" if correction_ok else "fail")
        if is_unsupported_case else "not_applicable",
        "success": success,
        "failure_category": case.get("failure_category"),
        "expected_correction": case.get("expected_correction"),
        "actual_status": result.get("status"), "actual_rows": result.get("rows"),
        "semantic_plan": result,
    }


def run_evaluation(*, cases_path: Path = CASES_PATH, output_path: Path = SUMMARY_PATH) -> dict[str, Any]:
    dataset = json.loads(cases_path.read_text(encoding="utf-8"))
    results = [run_case(case) for case in dataset["cases"]]
    categories = ("semantic_resolution", "sql_valid", "result_correct",
                 "clarification_behavior", "unsupported_query_handling")
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_version": dataset["dataset_version"],
        "active_model_version": registry["active_version"],
        "total_cases": len(results),
        "passed_cases": sum(item["success"] for item in results),
        "failed_cases": [item["id"] for item in results if not item["success"]],
        "category_pass_rates": {
            category: {
                "passed": sum(item[category] == "pass" for item in results),
                "applicable": sum(item[category] != "not_applicable" for item in results),
            }
            for category in categories
        },
        "cases": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case, outcome in zip(dataset["cases"], results, strict=True):
        if case.get("failure_category"):
            record_bad_case(
                question=case["question"], model_version=registry["active_version"],
                semantic_plan=case["intent"], generated_sql=outcome["semantic_plan"].get("sql"),
                failure_category=case["failure_category"],
                expected_correction=case["expected_correction"],
            )
    return summary
