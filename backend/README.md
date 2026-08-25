# Finance Innovation RAG

面向“银行业监管制度与统计报表可信 RAG 问答”赛题的项目仓库。

仓库按 6 个模块组织，当前模块1文档解析、模块2最小知识库链路和模块4可信回答链路已经具备可运行实现。

## 本次更新

本次已经完成以下整理：

1. 实现 Word、PDF、Excel 五种文件格式的统一解析流程
2. 新增 MySQL 规范化数据模型、增量解析、失败重试和质量报告
3. 保留条款层级、PDF 页码、Excel 多级表头、公式、单位、期间和单元格位置
4. 按项目目录输出模块2可直接消费的三个 JSONL 文件
5. 补充比赛演示前端与模块2最小知识库链路
6. 完成模块4证据约束生成、关键字段校验、置信度与拒答机制

## 当前项目定位

围绕赛题要求，项目按 6 个模块拆分：

1. 文档解析
2. 知识库构建与索引
3. 查询理解与混合检索
4. 答案生成与可信校验
5. 后端 API 与前端展示
6. 评测、实验与报告

## 项目目录

```text
app/
  parsing/        # 模块1：文档解析
  indexing/       # 模块2：知识库构建与索引
  retrieval/      # 模块3：查询理解与混合检索
  generation/     # 模块4：答案生成与可信校验
  api/            # 模块5：后端 API
  schemas/        # 共享数据结构
  shared/         # 通用工具
configs/          # 配置文件
data/
  raw/            # 原始数据（本地放置，大文件默认不提交）
    qa/
    nfra_page_attachments_500/
  parsed/         # 模块1输出
    docs/
    tables/
    meta/
  processed/      # 模块2输出
    chunks/
    kb/
    eval_ready/
  samples/        # 单元测试夹具，不作为模块交付路径
frontend/         # 比赛演示前端（Streamlit）
indexes/          # 检索索引产物
scripts/          # 命令行入口
tests/            # 测试
eval/             # 评测脚本
reports/          # 实验报告
slides/           # 答辩材料
docs/             # 协作与接口文档
```

## 数据接入约定

默认按以下方式接入数据：

1. QA 文件放到 `data/raw/qa/`
2. 原始监管附件放到 `data/raw/nfra_page_attachments_500/`
3. Word/PDF 解析结果写到 `data/parsed/docs/`
4. Excel 解析结果写到 `data/parsed/tables/`
5. 元数据写到 `data/parsed/meta/`
6. chunk 与知识库产物写到 `data/processed/chunks/` 和 `data/processed/kb/`
7. 清洗后的评测集写到 `data/processed/eval_ready/`

详细说明见：

- `docs/模块1项目介绍与模块2对接.md`
- `docs/module_contracts.md`
- `docs/模块4介绍与模块对接.md`
- `docs/module1_parsing_manual.md`
- `docs/frontend_plan.md`
- `docs/data_layout.md`

## 当前前端说明

仓库原本主要是后端与离线处理骨架，目前已经补充一个轻量的 `Streamlit` 演示前端，用于比赛阶段快速展示：

1. 问题输入
2. 回答结果
3. 证据列表
4. 风险提示

后续如果需要更完整的产品形态，可以再升级成 `FastAPI + React` 的前后端分离结构。

## 快速开始

### 1. 安装依赖

```powershell
pip install -r requirements.txt
```

`requirements.txt` 已包含模块2/模块3向量检索需要的 `numpy`、`sentence-transformers` 和 `faiss-cpu`。项目不要求团队成员固定使用 Conda；各成员可使用满足依赖兼容性的 Python 环境。Windows + Conda Python 3.11 仅是任务3负责人的本机开发和验证环境，不是其他模块的环境要求。

如果 PyPI 网络不可用，也可以改用 Conda 备用安装方式：

```powershell
conda install --override-channels -c pytorch -c conda-forge faiss-cpu=1.11.0 numpy=1.26.4 -y
```

### 2. 配置并运行模块1

数据库基础配置位于 `configs/parsing.json`，密码必须通过环境变量传入：

```powershell
$env:RAG_DB_PASSWORD="你的本地MySQL密码"
python scripts/parse_documents.py sync-raw
python scripts/parse_documents.py init-db
python scripts/parse_documents.py inventory
python scripts/parse_documents.py parse --all
python scripts/parse_documents.py export-jsonl
python scripts/parse_documents.py report
```

模块1数据流：

`data/raw -> finance_innovation_rag -> data/parsed/docs|tables|meta -> 模块2`

主要输出：

- `data/parsed/docs/parsed_docs.jsonl`
- `data/parsed/tables/table_evidence.jsonl`（模块2正式输入）
- `data/parsed/tables/parsed_tables.jsonl`（可选完整单元格归档）
- `data/parsed/meta/doc_meta.jsonl`
- `reports/module1_parsing_report.md`

### 3. 运行模块2

所有成员统一使用 `configs/default.json` 和 `data/parsed/`。模块1生成后，体积可接受的正文与元数据文件提交 Git；大体积表格文件由成员本地放到同一个标准目录：

```text
data/parsed/docs/parsed_docs.jsonl
data/parsed/tables/table_evidence.jsonl
```

文件齐备后运行：

```powershell
python scripts/build_kb.py
python scripts/search_kb.py "资本充足率" --top-k 5
python scripts/search_kb.py "商业银行应当如何管理资本" --chunk-type clause
```

项目不提供第二套模块交付路径。`data/samples/` 仅供自动化测试使用，模块2正式运行不得读取该目录。

### 4. 运行模块3

模块3直接消费模块2的正式知识库和向量索引：

```text
data/processed/kb_rebuild/metadata.db
indexes/kb_rebuild/
```

运行完整查询理解与检索管线：

```powershell
python scripts/retrieve.py "商业银行核心一级资本充足率最低要求是多少？" --top-k 5
python scripts/retrieve.py "2025年三季度商业银行资本充足率是多少？" --top-k 5
python scripts/evaluate_module3.py --top-k 5
python -m unittest tests.test_module1_parsing -v
python -m unittest tests.test_module2_smoke tests.test_module2_vector -v
python -m unittest tests.test_module3_retrieval -v
```

Windows 下 FAISS 与 Torch 可能分别加载不同 OpenMP 运行时，因此全项目测试按上述模块分进程执行；不要用 `KMP_DUPLICATE_LIB_OK=TRUE` 绕过运行时冲突。

模块3代码统一放在 `app/retrieval/`：

- `query_classifier.py`：问题分类
- `query_parser.py`：指标、日期、季度、文号、条款和运算符解析
- `metadata_filter.py` / `entity_filter.py`：元数据和实体强约束
- `bm25_retriever.py`：调用模块2的 FTS5/BM25 接口
- `vector_retriever.py`：调用模块2的真实 FAISS 向量接口
- `table_retriever.py`：按指标、报告期和表格结构二次排序
- `table_evidence.py`：严格期间匹配与行级证据的单元格裁剪
- `hybrid_retriever.py`：题型路由、RRF融合、故障降级和统一响应
- `reranker.py`：可插拔成对重排序接口
- `evidence_selector.py`：最小充分证据和来源完整性诊断

默认正式路径同时启用 BM25、向量和表格专用检索。向量索引或模型不可用时，完整响应会在 `diagnostics.failures` 中记录失败通道，并保留其余召回结果。

模块4正式接入应使用 `retrieve()` 的完整响应，并先处理 `answerable`、`degraded`、`needs_clarification`、`no_evidence` 四种状态。模块3能力说明与详细交接见 `docs/模块3项目介绍与模块4对接.md`。

模块3交付给模块4的关键约束：

- `module4_guidance.may_generate_answer=false` 时不得调用答案生成
- 指定银行档次的阈值题必须由同档次条款证据支撑
- 同一期间存在多个表格数值列时返回统计口径澄清，不默认选列
- 数值、单位、条款号和单元格引用保持源数据不变

任务4/任务5联调时可通过模块3 HTTP 检索接口获取同一完整响应：

```bat
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

```http
POST /api/v1/retrieve
Content-Type: application/json

{"question":"2025年三季度商业银行资本充足率是多少？","top_k":5}
```

该接口只返回任务3检索结果，不负责大模型答案生成；最终 `/api/v1/ask` 由任务5在接入任务4后负责。

### 5. 启动前端演示

```powershell
streamlit run frontend/app.py
```

模块4无需额外模型依赖即可运行保守的抽取式回答；接入大模型时可通过 `generate_answer(..., generator=...)` 注入生成函数，最终结果仍会经过关键字段校验。详细说明见 `app/generation/README.md`。

## 协作建议

建议 6 人团队按下面方式分工：

1. 数据治理与项目初始化
2. Excel 解析与表格结构化
3. Word/PDF 解析与条款结构化
4. 知识库与混合检索
5. 生成、校验与 API 编排
6. 前端展示、评测与答辩材料

当前离线链路为：

`多格式解析 -> MySQL规范化落库 -> JSONL交付 -> 知识库 -> 检索`

## 注意事项

1. 原始附件、超大 JSONL、数据库和索引产物默认不提交 Git
2. `parsed_docs.jsonl`、`doc_meta.jsonl` 和 `generated_manifest.jsonl` 体积可接受，应提交 Git
3. `table_evidence.jsonl` 和 `parsed_tables.jsonl` 体积较大，保持忽略并由成员本地放入标准目录
4. 如果新增字段或修改模块接口，先更新 `docs/module_contracts.md`
5. 数据库密码不得写入源码、配置文件、README 或提交记录

## 下一步建议

推荐优先完成以下事项：

1. 把 `QA数据.xlsx` 转成统一评测格式
2. 基于全量解析结果优化表格 chunk 和混合检索
3. 打通检索 -> 回答 -> 前端展示闭环
4. 使用种子问答建立解析与检索回归测试
