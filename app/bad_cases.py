"""Append and inspect reproducible semantic-query Bad Cases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "evaluation" / "bad-cases.jsonl"


def record_bad_case(*, question: str, model_version: str, semantic_plan: dict[str, Any] | None,
                    generated_sql: str | None, failure_category: str,
                    expected_correction: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": question,
        "model_version": model_version,
        "semantic_plan": semantic_plan,
        "generated_sql": generated_sql,
        "failure_category": failure_category,
        "expected_correction": expected_correction,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    for existing in read_bad_cases(path):
        if (existing.get("question"), existing.get("model_version"), existing.get("failure_category")) == (
            question, model_version, failure_category
        ):
            return existing
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_bad_cases(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
