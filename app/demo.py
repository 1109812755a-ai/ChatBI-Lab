"""Run the fixed competency-question path without a hosted model credential."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from app.agent import query_retail_data


def parse_demo_question(question: str, *, as_of: date | None = None) -> dict[str, Any]:
    text = question.casefold()
    metrics = []
    if "gmv" in text or "交易额" in question or "销售额" in question:
        metrics.append("GMV")
    if "订单数" in question or "order count" in text:
        metrics.append("OrderCount")
    if "销量" in question or "units sold" in text:
        metrics.append("UnitsSold")
    dimensions = []
    if "门店" in question or "store" in text:
        dimensions.append("Store")
    if "商品" in question or "product" in text:
        dimensions.append("Product")
    if "日期" in question or "按天" in question or "date" in text:
        dimensions.append("CalendarDate")
    if not metrics:
        return {"status": "clarification_required", "message": "请明确询问 GMV、订单数或销量。"}
    if not dimensions:
        return {"status": "clarification_required", "message": "请明确需要按门店、商品或日期查看。"}
    if "上个月" in question or "last month" in text:
        current = as_of or date.today()
        end = current.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        return query_retail_data.invoke({
            "metrics": metrics, "dimensions": dimensions,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        })
    return query_retail_data.invoke({"metrics": metrics, "dimensions": dimensions})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="+")
    parser.add_argument("--as-of", help="reference date for relative time, in YYYY-MM-DD")
    args = parser.parse_args()
    reference = date.fromisoformat(args.as_of) if args.as_of else None
    result = parse_demo_question(" ".join(args.question), as_of=reference)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "answered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
