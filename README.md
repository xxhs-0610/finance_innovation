# 面向银行业监管制度与统计报表的可信 RAG 问答系统 (RegTrust-RAG)

本项目面向“银行业监管制度与统计报表的可信 RAG 问答”赛题，针对传统大模型在金融监管与统计报表问答场景中存在的幻觉、数据口径模糊、无法精准溯源等行业痛点，构建了**标准前后端分离、金融级防幻觉、严格证据约束与全链路可信校验**的工业级 RAG 智能问答系统。

---

## 🏛️ 系统架构拓扑图

```text
比赛/
├── frontend/                     # 【标准独立前端工程】
│   ├── package.json              # 前端工程依赖与 npm 启动脚本 (dev / serve)
│   ├── index.html                # 前端三栏式 SPA 单页应用主入口
│   ├── src/                      # 前端规范分层源码
│   │   ├── assets/               # 静态资源与样式层 (variables.css, layout.css, components.css)
│   │   ├── utils/                # 通用工具层 (formatters.js, storage.js, event_bus.js)
│   │   ├── api/                  # 接口请求层 (http_client.js, rag_api.js, kb_api.js, import_api.js)
│   │   ├── router/               # 路由分发与 RBAC 权限守卫 (router.js)
│   │   ├── controllers/          # 控制层 (chat, import, kb, evidence, pipeline)
│   │   ├── components/           # UI 组件层 (toast.js, modal.js)
│   │   ├── state/                # 响应式状态中心 (app_state.js)
│   │   ├── services/             # 离线领域引擎 (mock_service.js)
│   │   └── main.js               # 前端应用主入口
│   └── README.md                 # 前端独立开发与运行指南
│
├── finance_innovation/           # 【核心后端与算法工程】
│   ├── app/                      # 后端标准分层源码
│   │   ├── controllers/          # 控制层 (health_controller, rag_controller, kb_controller, import_controller)
│   │   ├── services/             # 业务服务层 (rag_service, kb_service, parse_service)
│   │   ├── repositories/         # 数据持久层/DAO (sqlite_repo, meta_repo, vector_repo)
│   │   ├── parsing/              # 模块1：多格式文档与报表统一解析
│   │   ├── indexing/             # 模块2：知识库构建与 FAISS/BM25 索引
│   │   ├── retrieval/            # 模块3：查询理解与多路混合检索 (RRF + Rerank)
│   │   ├── generation/           # 模块4：大模型生成与事后防幻觉校验
│   │   ├── schemas/              # 跨模块数据契约 (Pydantic Models)
│   │   └── utils/                # 统一 REST 响应封装与异常拦截
│   ├── configs/                  # 统一配置层 (settings.py, default.json, parsing.json)
│   ├── scripts/                  # CLI 批处理与构建脚本 (build_kb.py, retrieve.py, parse_documents.py)
│   ├── tests/                    # 完整单元测试与接口契约测试套件
│   ├── data/                     # 结构化数据目录 (raw, parsed, processed, indexes)
│   ├── requirements.txt          # 后端依赖清单
│   └── README.md                 # 后端开发与各模块技术文档
│
└── 数据集和QA/                   # 原始文档附件与 QA 评测集
```

---

## 🎯 六大业务模块职责划分

| 模块序号 | 模块名称 | 核心职责 | 关键产出 |
| :--- | :--- | :--- | :--- |
| **模块 1** | **文档解析与结构化** | Word/PDF 监管制度与 Excel 统计报表的清洗、多级表头识别、单元格坐标绑定与 MySQL/JSONL 导出 | `parsed_docs.jsonl`, `table_evidence.jsonl`, `doc_meta.jsonl` |
| **模块 2** | **知识库构建与索引** | 条款与表格切片 (Chunking)、SQLite FTS5 全文索引构建、BGE 向量抽取与 FAISS 索引落盘 | `metadata.db`, `faiss.index`, `vector_meta.json` |
| **模块 3** | **查询理解与混合检索** | 用户意图识别（指标/期间/文号/机构）、BM25 + FAISS + 表格专用检索、RRF 倒数排名融合与 BGE-Rerank 重排 | `RetrievalResponse`（含 `answerable`, `needs_clarification`, `refused` 状态） |
| **模块 4** | **答案生成与可信校验** | 严格证据引用提示词工程、DeepSeek 大模型生成、数值/单位/文号事后强校验与库外拒答 | `AnswerResult`（带 `[E1]` 证据锚点与可信度评分） |
| **模块 5** | **前后端分离系统** | FastAPI 规范 RESTful 后端 + 白底专业三栏式 SPA 前端（对话窗/导入台/知识库/证据链/流水线） | 独立前端工程、统一 RESTful 接口与 Swagger API 文档 |
| **模块 6** | **评测与实验报告** | 评测集基准测试、检索命中率、数值核验准确率与答辩材料 | `reports/`, `eval/` |

---

## 🚀 快速启动指南

### 1. 启动后端 API 服务 (FastAPI)
```powershell
cd finance_innovation
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```
- API 接口文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

### 2. 启动独立前端工程
```powershell
cd frontend
npm run dev
# 或使用 Python 静态托管：
# python -m http.server 8080
```
在浏览器中访问：`http://localhost:8080`

### 3. 一键集成启动（前后端同端口预览）
```powershell
python finance_innovation/frontend/app.py
```

### 4. 运行全量自动化测试套件
```powershell
cd finance_innovation
python -m unittest tests.test_module1_parsing tests.test_module2_smoke tests.test_module3_api tests.test_module3_retrieval tests.test_module4_generation -v
```
