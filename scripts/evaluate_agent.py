"""Replay the versioned golden questions against the active semantic model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluation import run_evaluation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "data" / "evaluation" / "cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "evaluation" / "latest-summary.json")
    args = parser.parse_args()
    summary = run_evaluation(cases_path=args.cases, output_path=args.output)
    print(f"Evaluation {summary['dataset_version']}: {summary['passed_cases']}/{summary['total_cases']} passed.")
    print(f"Summary: {args.output}")
    return 0 if summary["passed_cases"] == summary["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
