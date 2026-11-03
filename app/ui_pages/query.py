"""Question workbench page."""

import streamlit as st

from app.agent import ask_stream
from app.demo import parse_demo_question
from app.settings import get_settings

SAMPLE_QUESTIONS = {
    "上个月按门店看 GMV 和销量": "按门店看上个月 GMV 和销量",
    "各门店订单数": "各门店的订单数",
    "按商品看销量": "按商品看销量",
    "GMV 按商品（需要澄清）": "按商品统计 GMV",
}


def _set_sample_question() -> None:
    selected = st.session_state.get("query_example")
    if selected:
        st.session_state.query_question = SAMPLE_QUESTIONS[selected]


def _render_query_result(result: dict, *, show_answer: bool = True) -> None:
    status = result.get("status")
    if status != "answered":
        message = result.get("message", "问题需要更多信息。")
        if status == "error":
            st.error(message)
        else:
            st.warning(message)
        return

    answer = result.get("answer")
    if answer and show_answer:
        st.markdown(answer)
    rows = result.get("rows")
    if rows is not None:
        st.subheader("查询结果")
        columns = st.columns(3)
        columns[0].metric("结果行数", result.get("row_count", len(rows)))
        columns[1].metric("模型版本", result.get("model_version", "—"))
        columns[2].metric("查询状态", "完成")
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("查询成功，但没有符合条件的记录。")

        if result.get("metrics"):
            st.subheader("指标口径")
            metric_columns = st.columns(min(3, len(result["metrics"])))
            for index, metric in enumerate(result["metrics"]):
                with metric_columns[index % len(metric_columns)]:
                    st.markdown(f"**{metric.get('label', metric['name'])}**")
                    st.caption(metric.get("definition", ""))
                    st.caption(f"粒度：{metric.get('grain', '未提供')}")
                    if metric.get("filters"):
                        st.caption("口径过滤：" + "；".join(metric["filters"]))

        with st.expander("查看语义计划、SQL 和参数"):
            if result.get("dimensions"):
                st.write("维度：", "、".join(result["dimensions"]))
            if result.get("time_range"):
                st.write("时间范围：", result["time_range"].get("start"), "至", result["time_range"].get("end"), "（结束日期不包含）")
            if result.get("semantic_filters"):
                st.write("过滤条件：")
                st.json(result["semantic_filters"])
            if result.get("sql"):
                st.code(result["sql"], language="sql")
                st.write("绑定参数：")
                st.json(result.get("parameters", []))
            if result.get("semantic_plan"):
                st.write("语义计划：")
                st.json(result["semantic_plan"])
            if result.get("truncated"):
                st.warning("结果达到行数上限，当前页面显示的结果可能不完整。")


def render() -> None:
    st.title("零售问数工作台")
    st.caption("使用已发布的业务语义模型查询本地合成零售数据。")
    mode = st.radio(
        "运行模式",
        ["本地演示（无需模型密钥）", "DeepAgents 自然语言问答"],
        horizontal=True,
        key="query_mode",
    )
    examples = list(SAMPLE_QUESTIONS)
    if "query_example" not in st.session_state:
        st.session_state.query_example = examples[0]
    if "query_question" not in st.session_state:
        st.session_state.query_question = SAMPLE_QUESTIONS[st.session_state.query_example]
    st.selectbox("示例问题", examples, key="query_example", on_change=_set_sample_question)
    question = st.text_area(
        "输入经营问题",
        height=90,
        key="query_question",
        help="示例覆盖 GMV、订单数、销量，以及门店和商品维度。",
    )

    model_ready = bool(get_settings().api_key)
    online_mode = mode.startswith("DeepAgents")
    if online_mode and not model_ready:
        st.info("DeepAgents 模式需要百炼 API Key。请将 `.env.example` 复制为 `.env`，填写 `DASHSCOPE_API_KEY` 后重新启动应用。")

    run = st.button("查询", type="primary", disabled=online_mode and not model_ready)
    streamed_answer_in_this_run = False
    if run:
        if not question.strip():
            st.warning("请先输入一个问题。")
        elif online_mode:
            streamed_answer_in_this_run = True
            answer_placeholder = st.empty()
            answer_parts: list[str] = []
            query_result = None
            terminal = None
            progress = st.status("正在准备 Agent…", expanded=True)
            try:
                for event in ask_stream(question):
                    event_type = event.get("type")
                    if event_type == "progress":
                        message = event.get("message", "正在处理…")
                        state = event.get("state")
                        if state == "completed":
                            progress.write("✓ " + message)
                        elif state == "needs_clarification":
                            progress.write("! " + message)
                        elif state == "failed":
                            progress.write("× " + message)
                        else:
                            progress.write("… " + message)
                        progress.update(label=message, state="running")
                    elif event_type == "answer_delta":
                        answer_parts.append(event.get("text", ""))
                        answer_placeholder.markdown("".join(answer_parts))
                    elif event_type == "query_result":
                        query_result = event.get("result")
                    elif event_type == "terminal":
                        terminal = event
                        if terminal.get("query_result") is not None:
                            query_result = terminal["query_result"]

                state = (terminal or {}).get("state", "error")
                answer = (terminal or {}).get("answer") or "".join(answer_parts)
                if state == "completed" and query_result:
                    query_result["answer"] = answer
                    st.session_state.query_result = query_result
                    progress.update(label="查询完成", state="complete", expanded=False)
                elif state == "clarification":
                    result = query_result or {"status": "clarification_required"}
                    result["message"] = result.get("message") or answer or "请补充问题中的指标或查询条件。"
                    result["answer"] = answer
                    st.session_state.query_result = result
                    progress.update(label="需要补充信息", state="complete", expanded=True)
                else:
                    message = (terminal or {}).get("message", "Agent 请求失败。")
                    st.session_state.query_result = {"status": "error", "message": message, "answer": answer}
                    progress.update(label="查询失败：" + message, state="error", expanded=True)
            except Exception as error:
                st.session_state.query_result = {"status": "error", "message": str(error), "answer": "".join(answer_parts)}
                progress.update(label="查询失败：" + str(error), state="error", expanded=True)
        else:
            try:
                with st.spinner("正在读取语义模型并查询数据…"):
                    st.session_state.query_result = parse_demo_question(question)
            except Exception as error:
                st.session_state.query_result = {"status": "error", "message": str(error)}

    result = st.session_state.get("query_result")
    if result:
        if result.get("status") == "answered":
            st.success("查询完成。")
        _render_query_result(result, show_answer=not streamed_answer_in_this_run)


render()
