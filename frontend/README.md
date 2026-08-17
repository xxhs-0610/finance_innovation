# RegTrust-RAG 前端系统使用与演示指南

面向“银行业监管制度与统计报表的可信 RAG 问答”赛题构建的产品级三栏前端系统。

## 🌟 核心功能与架构亮点

1. **白底产品化三栏设计**：
   - **左侧栏**：顶部一级功能菜单（对话窗 / 导入台 / 知识库 / 证据审查 / 模块对接），二级历史会话切换列表，底部“新建窗口”；
   - **中间栏**：主内容区（左右气泡问答、四类数据专属导入、知识库治理表格、严格单列证据流与动态原文高亮预览、五步模块流水线）；
   - **右侧栏**：随主视图联动的实时质检指标、存储分布、文档元数据与系统技术规范。
2. **RBAC 角色权限体系**：
   - **管理员 (Admin)**：全量权限（文件导入、知识库治理与删除、模块监控）；
   - **普通用户 (User)**：合规问答与证据查阅，管理入口受权限保护。
3. **金融级防幻觉与可信机制**：
   - 意图路由分类；
   - BM25 条款精准检索 + FAISS 语义检索 + BGE-Rerank 混合重排；
   - 严格拒答机制（库外问题阻断）；
   - 数字与强弱规范词事后校验。

---

## 🚀 启动与使用方式

### 方式一：直接在浏览器中打开（推荐，零环境依赖）
直接双击打开 `frontend/index.html` 或通过任意静态 Web 服务托管：

```powershell
# 在 frontend 目录下启动本地 HTTP 服务
cd frontend
python -m http.server 8080
```
在浏览器访问 `http://localhost:8080` 即可体验。

### 方式二：通过 Streamlit 运行

```powershell
streamlit run frontend/app.py
```

---

## 📁 目录结构

```text
frontend/
├── index.html                  # 页面主入口 (HTML5 语义化结构)
├── css/
│   ├── base.css                # 视觉设计系统与基础变量
│   ├── layout.css              # 三栏布局、顶部栏与响应式规范
│   └── components.css          # 聊天气泡、导入队列、单列证据卡片与模态框
├── js/
│   ├── state.js                # 全局响应式状态管理中心
│   ├── mock_service.js         # 内置高保真 Mock 检索与生成引擎 (防幻觉/拒答模拟)
│   ├── api_service.js          # 后端 FastAPI / Python API 智能对接层
│   ├── controllers/
│   │   ├── chat_controller.js  # 对话流、示例问题、证据联动与指标同步
│   │   ├── import_controller.js# Word/PDF/Excel/QA 导入与队列动态模拟
│   │   ├── kb_controller.js    # 知识库文档检索、切片查看与增删改查
│   │   ├── evidence_controller.js # 单列证据审查与原文片段高亮
│   │   └── pipeline_controller.js # 模块对接流水线与接口契约
│   └── app.js                  # 应用主入口、权限守卫与路由分发
├── app.py                      # Streamlit 兼容与演示运行脚本
└── README.md                   # 说明文档
```
