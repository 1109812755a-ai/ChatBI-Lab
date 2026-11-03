"""DeepAgents orchestration for resolving retail questions into semantic plans."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from typing import Any, Iterator

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.tools import tool
from pydantic import StrictInt

from app.semantic import SemanticResolutionError, build_query_plan, metric_catalog
from app.progress import emit_progress
from app.settings import get_settings
from app.sql import execute_plan_dict


def previous_calendar_month(today: date | None = None) -> dict[str, str]:
    current = today or date.today()
    first_this_month = current.replace(day=1)
    first_last_month = (first_this_month - timedelta(days=1)).replace(day=1)
    return {"start": first_last_month.isoformat(), "end": first_this_month.isoformat(), "end_exclusive": "true"}


@tool
def resolve_semantic_plan(
    metrics: list[str],
    dimensions: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    time_period: str | None = None,
    filters: list[dict[str, str]] | None = None,
    order_by: dict[str, str] | None = None,
    limit: StrictInt | None = None,
) -> dict[str, Any]:
    """Resolve requested retail metrics and dimensions against the active published ontology.

    Use for business questions about GMV, order count, or units sold, grouped by
    store, product, or calendar date. Supply a half-open date range as ISO dates
    when the user mentions a time period. Returns an explicit clarification or
    unsupported-term result rather than guessing. Optional order_by accepts a
    requested metric and asc/desc direction; limit accepts 1 through 500 rows.
    """
    time_range = None
    if time_period:
        if time_period.casefold() not in {"previous_month", "last_month", "上个月", "上月"}:
            return {"status": "unsupported", "message": "当前只支持明确日期范围或上个月。"}
        time_range = previous_calendar_month()
    if start_date or end_date:
        if time_period:
            return {"status": "clarification_required", "message": "请使用相对时间或明确日期范围其中一种。"}
        if not start_date or not end_date:
            return {"status": "clarification_required", "message": "请提供完整的开始和结束日期。"}
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            return {"status": "clarification_required", "message": "日期需使用 YYYY-MM-DD 格式。"}
        if start >= end:
            return {"status": "clarification_required", "message": "结束日期必须晚于开始日期。"}
        time_range = {"start": start.isoformat(), "end": end.isoformat(), "end_exclusive": "true"}
    emit_progress("semantic_resolution", "started", "正在查询本体和语义模型")
    try:
        plan = build_query_plan(metrics, dimensions, time_range=time_range, filters=filters,
                                order_by=order_by, limit=limit)
    except SemanticResolutionError as error:
        emit_progress("semantic_resolution", "needs_clarification", "本体解析需要澄清")
        return {"status": "clarification_required", "message": str(error)}
    emit_progress(
        "semantic_resolution", "completed", "本体和语义模型解析完成",
        model_version=plan.model_version,
        metrics=[metric.name for metric in plan.metrics],
        dimensions=[dimension["name"] for dimension in plan.dimensions],
    )
    emit_progress(
        "query_plan", "completed", "查询计划已生成",
        model_version=plan.model_version,
        metrics=[metric.name for metric in plan.metrics],
        dimensions=[dimension["name"] for dimension in plan.dimensions],
    )
    return {"status": "resolved", **plan.to_dict()}


@tool
def list_supported_metrics() -> list[dict[str, Any]]:
    """List the metrics in the active published semantic model with definitions and grains."""
    return metric_catalog()


@tool
def query_retail_data(
    metrics: list[str],
    dimensions: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    time_period: str | None = None,
    filters: list[dict[str, str]] | None = None,
    order_by: dict[str, str] | None = None,
    limit: StrictInt | None = None,
) -> dict[str, Any]:
    """Resolve a retail question against the ontology and run a bounded read-only query.

    Use only for supported metrics (GMV, order count, units sold) and dimensions
    (store, product, calendar date). Filters are restricted to mapped fields.
    Optional order_by ranks by a requested metric using asc/desc; limit requests
    1 through 500 rows. Returns data rows together with definitions and
    model-version provenance.
    """
    plan_result = resolve_semantic_plan.invoke({
        "metrics": metrics, "dimensions": dimensions,
        "start_date": start_date, "end_date": end_date,
        "time_period": time_period, "filters": filters,
        "order_by": order_by, "limit": limit,
    })
    if plan_result.get("status") != "resolved":
        return plan_result
    try:
        return {"status": "answered", **execute_plan_dict(plan_result)}
    except (SemanticResolutionError, ValueError) as error:
        return {"status": "unsupported", "message": str(error)}


SYSTEM_PROMPT = """You are a retail data-question assistant. Resolve business meaning from the published semantic model by calling the provided tools. Never invent metric formulas or source mappings. For questions requesting results, call query_retail_data and base the answer only on its rows and provenance. If a request is ambiguous or unsupported, ask a concise clarification. For 'last month' / '上个月', pass time_period='previous_month'; for a named store filter, use the mapped store_code filter. For ranking questions, set order_by to a requested metric and direction ('desc' for highest/top, 'asc' for lowest/bottom). Convert an explicit Top N count to limit=N; for a singular superlative such as 'largest store' or 'GMV 最大的门店', use limit=1. Only order by a metric included in metrics. Do not set order_by or limit when the user did not request ranking or a row count. Explain each metric's definition and model version briefly."""


def build_agent(*, model_override: Any = None):
    settings = get_settings()
    model_key = settings.model
    if settings.api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.api_key)
    if settings.base_url:
        os.environ.setdefault("OPENAI_BASE_URL", settings.base_url)
    register_harness_profile(
        model_key,
        HarnessProfile(
            excluded_tools=frozenset({"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute", "task"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    return create_deep_agent(
        model=model_override or model_key,
        tools=[resolve_semantic_plan, list_supported_metrics, query_retail_data],
        # DeepAgents requires its filesystem middleware to retain read_file;
        # the harness profile below keeps even that read-only tool invisible.
        middleware=[FilesystemMiddleware(tools=["read_file"])],
        system_prompt=SYSTEM_PROMPT,
        subagents=[],
        name="retail-semantic-query-agent",
    )


def _extract_query_result(messages: list[Any]) -> dict[str, Any] | None:
    query_result = None
    for message in messages:
        candidate = _query_result_from_message(message)
        if candidate is not None:
            query_result = candidate
    return query_result


def _query_result_from_message(message: Any) -> dict[str, Any] | None:
    if getattr(message, "type", None) != "tool" or getattr(message, "name", None) != "query_retail_data":
        return None
    content = getattr(message, "content", None)
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return None
    return content if isinstance(content, dict) else None


def _text_from_message_chunk(message: Any) -> str:
    """Return only plain user-facing text, never tool-call or reasoning payloads."""
    if getattr(message, "type", None) not in {"ai", "AIMessageChunk"}:
        return ""
    if getattr(message, "tool_calls", None) or getattr(message, "tool_call_chunks", None):
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
        )
    return ""


def _message_has_tool_call(message: Any) -> bool:
    return bool(getattr(message, "tool_calls", None) or getattr(message, "tool_call_chunks", None))


def _messages_from_update(update: Any) -> list[Any]:
    if not isinstance(update, dict):
        return []
    messages: list[Any] = []
    for node_update in update.values():
        if isinstance(node_update, dict):
            values = node_update.get("messages", [])
            if isinstance(values, list):
                messages.extend(values)
    return messages


def _stream_is_unsupported(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    message = str(error).casefold()
    unsupported_language = any(term in message for term in (
        "stream not supported", "streaming not supported", "does not support stream",
        "unsupported stream", "stream parameter is not supported",
    ))
    return status in {400, 404, 405, 422} and unsupported_language


def ask_stream(question: str) -> Iterator[dict[str, Any]]:
    """Yield normalized progress, answer, query-result, and terminal events."""
    if not question.strip():
        raise ValueError("Question cannot be empty.")
    yield {"type": "progress", "stage": "planning", "state": "started", "message": "正在理解问题"}
    answer_parts: list[str] = []
    query_result = None
    query_started = False
    last_query_result: str | None = None
    try:
        agent = build_agent()
        stream = agent.stream(
            {"messages": [{"role": "user", "content": question}]},
            stream_mode=["messages", "updates", "custom"],
            version="v2",
        )
        for chunk in stream:
            if not isinstance(chunk, dict):
                continue
            event_type = chunk.get("type")
            data = chunk.get("data")
            if event_type == "custom":
                if isinstance(data, dict) and data.get("type") == "progress":
                    if data.get("stage") in {"semantic_resolution", "query_plan", "sql_compilation", "sql_validation", "database_execution"}:
                        query_started = True
                    yield data
            elif event_type == "messages" and isinstance(data, tuple) and data:
                message = data[0]
                if _message_has_tool_call(message):
                    query_started = True
                text = _text_from_message_chunk(message)
                if text:
                    answer_parts.append(text)
                    yield {"type": "answer_delta", "text": text}
            elif event_type == "updates":
                for message in _messages_from_update(data):
                    candidate = _query_result_from_message(message)
                    if candidate is not None:
                        query_result = candidate
                        serialized = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
                        if serialized != last_query_result:
                            last_query_result = serialized
                            query_started = True
                            yield {"type": "query_result", "result": candidate}
        status = (query_result or {}).get("status")
        terminal_state = "completed" if status == "answered" else (
            "clarification" if status in {"clarification_required", "unsupported"} or not query_result
            else "error"
        )
        yield {
            "type": "terminal", "state": terminal_state,
            "answer": "".join(answer_parts), "query_result": query_result,
        }
    except Exception as error:
        if _stream_is_unsupported(error) and not query_started and not answer_parts:
            yield {"type": "progress", "stage": "fallback", "state": "started",
                   "message": "当前模型不支持流式请求，切换普通输出"}
            try:
                result = ask(question)
                answer = result.get("answer", "")
                query_result = result.get("query_result")
                if answer:
                    yield {"type": "answer_delta", "text": answer}
                if query_result:
                    yield {"type": "query_result", "result": query_result}
                state = "completed" if (query_result or {}).get("status") == "answered" else "clarification"
                yield {"type": "terminal", "state": state, "answer": answer, "query_result": query_result}
            except Exception as fallback_error:
                yield {"type": "terminal", "state": "error", "message": str(fallback_error)}
        else:
            yield {"type": "terminal", "state": "error", "message": str(error)}


def ask(question: str) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("Question cannot be empty.")
    agent = build_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    messages = result.get("messages", [])
    final = messages[-1].content if messages else ""
    return {
        "question": question,
        "model": get_settings().model,
        "answer": final,
        "query_result": _extract_query_result(messages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="+")
    args = parser.parse_args()
    question = " ".join(args.question)
    try:
        print(json.dumps(ask(question), ensure_ascii=False, indent=2, default=str))
    except Exception as error:
        print(f"Agent invocation failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
