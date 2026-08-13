from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.main import ask


st.set_page_config(
    page_title="RegTrust-RAG Demo",
    page_icon="🏦",
    layout="wide",
)


def render_evidence(evidence: list[dict]) -> None:
    if not evidence:
        st.info("当前没有返回证据。")
        return

    for idx, item in enumerate(evidence, start=1):
        source = item.get("source", {})
        title = source.get("title", "未命名来源")
        chunk_type = item.get("chunk_type", "unknown")
        score = item.get("score", 0.0)
        header = f"证据 {idx} | {title} | {chunk_type} | score={score:.3f}"
        with st.expander(header):
            st.write(item.get("text", ""))
            st.caption(
                " / ".join(
                    [
                        f"doc_id: {source.get('doc_id', '-')}",
                        f"条款: {source.get('clause_no', '-')}",
                        f"sheet: {source.get('sheet_name', '-')}",
                        f"table: {source.get('table_name', '-')}",
                        f"cell: {source.get('cell_ref', '-')}",
                    ]
                )
            )
            st.caption(f"路径: {source.get('local_path', '-')}")


st.title("RegTrust-RAG 比赛演示界面")
st.caption("面向银行业监管制度与统计报表的可信 RAG 问答系统 Demo")

with st.sidebar:
    st.subheader("当前形态")
    st.write("该前端直接调用 `app.api.main.ask()`，用于串起检索、回答与证据展示。")
    st.subheader("适合展示的能力")
    st.markdown(
        "- 问题输入\n"
        "- 返回答案\n"
        "- 展示证据\n"
        "- 展示风险提示\n"
        "- 为后续拒答、置信度、原文预览留接口"
    )
    st.subheader("建议演示问题")
    st.markdown(
        "- 商业银行应当如何管理资本？\n"
        "- 资本充足率相关监管条款是什么？\n"
        "- 2025年商业银行主要监管指标情况表里有哪些核心指标？"
    )

left, right = st.columns([3, 2])

with left:
    question = st.text_area(
        "请输入问题",
        placeholder="例如：商业银行应当如何管理资本？",
        height=120,
    )
    run = st.button("开始问答", type="primary", use_container_width=True)

with right:
    st.subheader("当前链路")
    st.code(
        "问题输入 -> 混合检索 -> 证据包 -> 回答生成 -> 风险提示/拒答",
        language="text",
    )

if run:
    if not question.strip():
        st.warning("请先输入问题。")
    else:
        with st.spinner("正在检索证据并生成回答..."):
            result = ask(question.strip())

        st.subheader("回答结果")
        status = result.get("status", "unknown")
        if status == "answered":
            st.success("已生成回答")
        elif status == "refused":
            st.error("当前触发拒答")
        else:
            st.info(f"当前状态：{status}")

        st.write(result.get("answer", ""))

        risk_tips = result.get("risk_tips", [])
        if risk_tips:
            st.subheader("风险提示")
            for tip in risk_tips:
                st.warning(tip)

        st.subheader("证据列表")
        render_evidence(result.get("evidence", []))
