from __future__ import annotations

import os
from pathlib import Path
import sys
import webbrowser

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.api.main import ask
except ImportError:
    def ask(q: str):
        return {"status": "answered", "answer": f"本地模式回答：{q}", "evidence": []}


st.set_page_config(
    page_title="RegTrust-RAG 银行业监管与报表可信问答",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Read the modern productized HTML frontend
FRONTEND_DIR = Path(__file__).resolve().parent
INDEX_HTML = FRONTEND_DIR / "index.html"

st.sidebar.title("🏦 RegTrust-RAG 控制台")
mode = st.sidebar.radio(
    "选择演示界面模式",
    ["🌟 产品级现代化三栏 Web 界面 (推荐)", "📊 Streamlit 原生问答调试模式"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    **系统核心特性：**
    - **白底高质感三栏布局**：对话窗 / 导入台 / 知识库 / 证据审查 / 模块对接
    - **RBAC 角色权限**：管理员全量治理 vs 普通用户合规查询
    - **混合检索架构**：BM25 条款精确检索 + FAISS 向量语义检索
    - **可信防幻觉**：数字核验、条文双向定位与严格拒答机制
    """
)

if mode == "🌟 产品级现代化三栏 Web 界面 (推荐)":
    # Render modern SPA web app
    if INDEX_HTML.exists():
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html_code = f.read()
        
        # Replace relative paths with inline base or serve seamlessly
        components.html(html_code, height=920, scrolling=True)
    else:
        st.error("未找到 index.html，请确保前端文件完整。")

else:
    # Streamlit Native Debug Mode
    st.title("RegTrust-RAG 原生问答调试台")
    st.caption("面向银行业监管制度与统计报表的可信 RAG 问答系统")

    col_q, col_s = st.columns([3, 1])
    with col_q:
        question = st.text_area(
            "请输入监管制度或统计报表问题：",
            placeholder="例如：商业银行应当如何管理资本？核心一级资本充足率底线是多少？",
            height=100
        )
    with col_s:
        st.markdown("**精选提问：**")
        if st.button("商业银行资本管理要求", use_container_width=True):
            question = "商业银行应当如何管理资本？核心一级资本充足率和总资本充足率的监管底线分别是多少？"
        if st.button("2025主要监管指标情况", use_container_width=True):
            question = "2025年商业银行主要监管指标情况表里，资产质量与风险抵补核心指标表现如何？"

    if st.button("开始检索与生成回答", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("请先输入问题。")
        else:
            with st.spinner("正在执行意图识别、混合检索、精重排与合规校验..."):
                res = ask(question.strip())
            
            st.subheader("💡 核心回答")
            st.write(res.get("answer", res.get("conclusion", "")))

            evidence = res.get("evidence", [])
            if evidence:
                st.subheader(f"📄 关联证据 ({len(evidence)} 条)")
                for idx, ev in enumerate(evidence, 1):
                    src = ev.get("source", {})
                    with st.expander(f"证据 {idx} | {src.get('title', '监管文件')} | score={ev.get('score', 0.9):.3f}"):
                        st.write(ev.get("text", ""))
                        st.caption(f"条款: {src.get('clause_no', '-')} | 表格: {src.get('table_name', '-')} | 路径: {src.get('local_path', '-')}")
