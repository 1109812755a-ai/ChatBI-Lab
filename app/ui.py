"""Local Streamlit entry point for the retail semantic data workbench."""

from __future__ import annotations

import streamlit as st


def main() -> None:
    st.set_page_config(
        page_title="零售语义问数工作台",
        page_icon="🛒",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    pages = st.navigation(
        {
            "问数": [st.Page("ui_pages/query.py", title="问数工作台", url_path="query", icon="💬", default=True)],
            "语义模型": [st.Page("ui_pages/model.py", title="语义模型", url_path="model", icon="🧩")],
            "质量与评估": [st.Page("ui_pages/evaluation.py", title="评估与 Bad Case", url_path="evaluation", icon="📊")],
        }
    )
    pages.run()


if __name__ == "__main__":
    main()
