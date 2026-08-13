# Finance Innovation RAG

面向“银行业监管制度与统计报表可信 RAG 问答”赛题的项目仓库。

这个仓库当前的目标不是一次性塞满全部实现，而是先搭好一个适合 6 人并行协作、可持续扩展、可快速演示的工程骨架。

## 本次更新

本次已经完成以下整理：

1. 拉取并初始化项目仓库
2. 补充比赛演示前端 `frontend/`
3. 完善数据目录结构，新增 `data/raw / parsed / processed`
4. 增加数据接入说明与前端说明文档
5. 更新 `.gitignore`，避免把原始大数据、索引和运行产物直接提交到仓库

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
  samples/        # 最小可运行样例
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

- `docs/module_contracts.md`
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

### 2. 运行模块 2 的最小样例

```powershell
python scripts/build_kb.py --sample
python scripts/search_kb.py "资本充足率" --top-k 5
python scripts/search_kb.py "商业银行应当如何管理资本" --chunk-type clause
```

### 3. 启动前端演示

```powershell
streamlit run frontend/app.py
```

## 协作建议

建议 6 人团队按下面方式分工：

1. 数据治理与项目初始化
2. Excel 解析与表格结构化
3. Word/PDF 解析与条款结构化
4. 知识库与混合检索
5. 生成、校验与 API 编排
6. 前端展示、评测与答辩材料

当前最适合先推进的是 Excel QA MVP，先打通：

`Excel解析 -> 表格知识库 -> 检索 -> 回答 -> 前端展示 -> 评测`

## 注意事项

1. `data/raw/` 下的真实原始数据默认不直接提交到 Git
2. 索引、数据库和运行产物默认不提交
3. 如果新增字段或修改模块接口，先更新 `docs/module_contracts.md`

## 下一步建议

推荐优先完成以下事项：

1. 生成原始文件 `manifest`
2. 把 `QA数据.xlsx` 转成统一评测格式
3. 优先完成 Excel 解析链路
4. 打通检索 -> 回答 -> 前端展示闭环
