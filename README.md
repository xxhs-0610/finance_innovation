# Finance Innovation RAG

面向银行业监管制度与统计报表的可信 RAG 问答系统项目骨架。

本项目按比赛链路拆成 6 个模块，方便团队成员并行开发：

1. 模块1：文档解析，把 Word / PDF / Excel 解析成结构化 JSONL
2. 模块2：知识库与索引，把结构化数据切成 chunk 并建立检索索引
3. 模块3：查询理解与混合检索，把用户问题变成证据包
4. 模块4：生成与可信校验，基于证据生成可核验答案
5. 模块5：API 与前端展示，提供演示系统
6. 模块6：评测、实验与报告，证明系统效果

当前已优先实现模块2的最小可运行版本：从样例 `parsed_docs.jsonl` / `parsed_tables.jsonl` 构建条款 chunk、表格 chunk、元数据库和 SQLite FTS5 检索索引。

## 快速开始

```powershell
python scripts/build_kb.py --sample
python scripts/search_kb.py "资本充足率" --top-k 5
python scripts/search_kb.py "商业银行应当如何管理资本" --chunk-type clause
```

如果你使用 Codex 内置 Python，可以替换成工作区提供的 Python 路径。

## 项目目录

```text
app/
  parsing/       # 模块1：文档解析
  indexing/      # 模块2：知识库构建与索引
  retrieval/     # 模块3：查询理解与混合检索
  generation/    # 模块4：答案生成与可信校验
  api/           # 模块5：后端 API
  schemas/       # 跨模块共享数据结构
  shared/        # 通用工具
configs/         # 配置文件
data/
  parsed/        # 模块1输出
  processed/     # 模块2输出
  samples/       # 可跑通的样例数据
indexes/         # 检索索引
scripts/         # 命令行入口
tests/           # 测试
eval/            # 模块6评测脚本
reports/         # 实验报告
slides/          # 答辩材料
docs/            # 协作接口文档
```

## 模块2交付物

模块2输出这些文件给模块3使用：

```text
data/processed/clause_chunks.jsonl
data/processed/table_chunks.jsonl
data/processed/metadata.db
indexes/bm25_corpus.jsonl
```

其中 `metadata.db` 内包含：

- `chunks`：所有 chunk 的元数据和原文定位
- `chunk_fts`：用于关键词召回的全文检索表

## 团队协作约定

- 模块1只需要稳定输出 `data/parsed/parsed_docs.jsonl`、`data/parsed/parsed_tables.jsonl`、`data/parsed/doc_meta.jsonl`
- 模块2不要反向修改模块1输出，只做清洗、chunk、索引和元数据挂载
- 模块3只通过 `app.indexing.index_reader.KnowledgeBaseReader` 或约定后的检索接口读取知识库
- 任何模块新增字段，先更新 `docs/module_contracts.md`

