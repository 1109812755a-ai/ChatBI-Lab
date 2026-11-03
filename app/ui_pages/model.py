"""Semantic model inspection and SHACL validation page."""

from __future__ import annotations

import json

import streamlit as st

from app.semantic import SemanticResolutionError, build_query_plan, metric_catalog
from scripts.model_registry import REGISTRY, rollback, version_dir
from scripts.validate_model import validate_model


def _load_registry() -> dict:
    if not REGISTRY.exists():
        return {"active_version": None, "versions": {}, "history": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _render_metrics(version: str) -> None:
    try:
        catalog = metric_catalog(version)
        summaries = []
        for item in catalog:
            name = item["iri"].rsplit("#", 1)[-1]
            plan = build_query_plan(name, [], version=version).metrics[0]
            summaries.append((item, plan))
    except (SemanticResolutionError, OSError, ValueError) as error:
        st.warning(f"无法读取此版本的语义目录：{error}")
        return

    if not summaries:
        st.info("该版本没有可浏览的指标。")
        return
    for item, plan in summaries:
        with st.container(border=True):
            st.subheader(plan.label)
            st.write(plan.definition)
            first, second = st.columns(2)
            first.caption(f"原生粒度：{plan.grain}")
            second.caption("支持维度：" + "、".join(plan.supported_dimensions))
            st.markdown("**必需过滤**")
            st.write("；".join(plan.filters))
            st.markdown("**来源字段**")
            st.dataframe(plan.source_fields, width="stretch", hide_index=True)
            with st.expander("查看 RDF 计划和关系映射"):
                st.json({
                    "metric_iri": item["iri"],
                    "expression": plan.expression,
                    "source_fields": plan.source_fields,
                    "required_relationships": plan.required_relationships,
                })


def _render_validation(version: str) -> None:
    key = f"validation:{version}"
    if st.button("运行 SHACL 校验", key=f"validate:{version}"):
        directory = version_dir(version)
        try:
            conforms, report = validate_model(directory)
            st.session_state[key] = {"conforms": conforms, "report": report}
        except Exception as error:
            st.session_state[key] = {"conforms": False, "report": str(error)}
    result = st.session_state.get(key)
    if result:
        if result["conforms"]:
            st.success(f"模型 {version} 符合 SHACL 约束。")
        else:
            st.error(f"模型 {version} 未通过 SHACL 校验。")
        st.code(result["report"], language="text")


def _clear_pending_version() -> None:
    st.session_state.pop("pending_model_version", None)


def _render_version_selection(records: dict, active: str | None) -> None:
    versions = sorted(records, reverse=True)
    target = st.selectbox(
        "切换活动模型",
        versions,
        index=versions.index(active) if active in versions else 0,
        key="model_switch_target",
        on_change=_clear_pending_version,
    )
    record = records[target]
    eligible = record.get("status") in {"active", "published"} and bool(
        (record.get("validation") or {}).get("conforms")
    )
    if target == active:
        st.caption("该版本当前已经处于活动状态。")
    elif not eligible:
        st.warning("此版本尚未发布或未通过 SHACL 校验，不能切换为活动版本。")
    elif st.button("申请切换", disabled=not eligible, key="request-model-switch"):
        st.session_state.pending_model_version = target

    pending = st.session_state.get("pending_model_version")
    if pending:
        st.warning(f"确认将活动模型从 {active} 切换到 {pending}？后续查询会使用新版本。")
        confirm, cancel = st.columns(2)
        if confirm.button("确认切换", type="primary", key="confirm-model-switch"):
            try:
                rollback(pending)
                st.session_state.pop("pending_model_version", None)
                st.success(f"已切换到模型 {pending}。")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        if cancel.button("取消", key="cancel-model-switch"):
            st.session_state.pop("pending_model_version", None)
            st.rerun()


def render() -> None:
    st.title("语义模型")
    st.caption("查看发布版本中的指标口径、RDF 映射和 SHACL 校验状态。")
    registry = _load_registry()
    records = registry.get("versions", {})
    active = registry.get("active_version")
    if not records:
        st.warning("还没有登记模型版本。请先在终端运行 model_registry.py bootstrap 1.0。")
        return

    versions = sorted(records, reverse=True)
    selected = st.selectbox("查看模型版本", versions, index=versions.index(active) if active in versions else 0)
    record = records[selected]
    status = record.get("status", "unknown")
    top = st.columns(3)
    top[0].metric("活动版本", active or "未发布")
    top[1].metric("当前查看", selected)
    top[2].metric("版本状态", status)

    with st.expander("选择活动版本", expanded=False):
        _render_version_selection(records, active)

    validation = record.get("validation") or {}
    if validation:
        if validation.get("conforms"):
            st.success("注册表中的最近校验结果：通过")
        else:
            st.error("注册表中的最近校验结果：未通过")
            if validation.get("report"):
                st.code(validation["report"], language="text")

    if status in {"active", "published"}:
        _render_metrics(selected)
    else:
        st.info("候选版本尚未发布；校验后发布，才能作为问数模型使用。")
    _render_validation(selected)


render()
