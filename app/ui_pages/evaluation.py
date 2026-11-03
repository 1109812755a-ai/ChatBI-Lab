"""Golden-set evaluation and Bad Case review page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.bad_cases import DEFAULT_PATH, read_bad_cases
from app.evaluation import SUMMARY_PATH, run_evaluation


def _load_summary() -> dict | None:
    if not SUMMARY_PATH.exists():
        return None
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        st.warning(f"无法读取上次评估摘要：{error}")
        return None


def _render_summary(summary: dict) -> None:
    passed = summary.get("passed_cases", 0)
    total = summary.get("total_cases", 0)
    failed = summary.get("failed_cases", [])
    st.subheader("评估运行结果")
    st.success(f"评估完成：{passed}/{total} 条通过。" if passed == total else f"评估完成：{passed}/{total} 条通过，{len(failed)} 条失败。")
    cards = st.columns(4)
    cards[0].metric("通过", passed)
    cards[1].metric("失败", len(failed))
    cards[2].metric("数据集版本", summary.get("dataset_version", "未知"))
    cards[3].metric("活动模型", summary.get("active_model_version", "未知"))
    st.caption(f"运行时间：{summary.get('evaluated_at', '未知')}")

    rates = summary.get("category_pass_rates", {})
    if rates:
        st.markdown("**分类通过率**")
        st.dataframe(
            pd.DataFrame([
                {"检查项": name, "通过": item.get("passed", 0), "适用": item.get("applicable", 0),
                 "通过率": f"{item.get('passed', 0)}/{item.get('applicable', 0)}"}
                for name, item in rates.items()
            ]),
            width="stretch", hide_index=True,
        )

    cases = summary.get("cases", [])
    if cases:
        st.markdown("**逐题结果**")
        st.dataframe(pd.DataFrame([
            {"问题": case.get("question"), "状态": "通过" if case.get("success") else "失败",
             "语义解析": case.get("semantic_resolution"), "SQL 校验": case.get("sql_valid"),
             "结果正确": case.get("result_correct"), "澄清行为": case.get("clarification_behavior"),
             "案例 ID": case.get("id")}
            for case in cases
        ]), width="stretch", hide_index=True)
    if failed:
        st.error("失败案例：" + "、".join(failed))
        for case in cases:
            if case.get("id") in failed:
                with st.expander(f"失败：{case.get('question', case.get('id'))}", expanded=True):
                    st.write("实际状态：", case.get("actual_status"))
                    st.write("期望修正：", case.get("expected_correction") or "未记录")
                    st.json(case.get("semantic_plan", {}))


def _render_bad_cases() -> None:
    st.subheader("Bad Case 来源记录")
    records = read_bad_cases()
    if not records:
        st.info("当前没有 Bad Case 记录。运行黄金集评估后，需澄清或暂不支持的问题会写入本地记录。")
        return
    labels = [f"{index + 1}. [{item.get('failure_category', '未分类')}] {item.get('question', '')}" for index, item in enumerate(records)]
    selected = st.selectbox("选择案例", range(len(records)), format_func=lambda index: labels[index], key="bad_case_selection")
    item = records[selected]
    cols = st.columns(3)
    cols[0].metric("模型版本", item.get("model_version", "未知"))
    cols[1].metric("失败类别", item.get("failure_category", "未分类"))
    cols[2].caption("记录时间：" + item.get("recorded_at", "未知"))
    st.markdown("**问题**")
    st.write(item.get("question", ""))
    st.markdown("**预期修正**")
    st.write(item.get("expected_correction", "未记录"))
    plan = item.get("semantic_plan")
    st.markdown("**语义计划 / 依据**")
    st.json(plan if plan is not None else {"提示": "该案例没有可序列化的语义计划。"})
    if item.get("generated_sql"):
        st.markdown("**生成 SQL**")
        st.code(item["generated_sql"], language="sql")
    else:
        st.caption("该案例在生成 SQL 前进入澄清，因此没有 SQL。")
    st.caption(f"本地记录文件：{DEFAULT_PATH.name}")


def render() -> None:
    st.title("评估与 Bad Case")
    st.caption("回放本地黄金问题集，检查语义解析、只读 SQL、结果和澄清行为。评估使用合成零售数据。")
    if st.button("运行黄金集评估", type="primary", key="run-golden-evaluation"):
        try:
            with st.spinner("正在运行评估…"):
                st.session_state["evaluation_summary"] = run_evaluation()
            st.session_state["evaluation_error"] = None
        except Exception as error:
            st.session_state["evaluation_error"] = str(error)
    if st.session_state.get("evaluation_error"):
        st.error("评估未完成：" + st.session_state["evaluation_error"])
    summary = st.session_state.get("evaluation_summary") or _load_summary()
    if summary:
        _render_summary(summary)
    _render_bad_cases()


render()
