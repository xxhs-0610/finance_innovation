# Data Layout

本文档说明项目数据如何落位到仓库结构中。

## 目录约定

### 原始数据

```text
data/raw/
  qa/
    QA数据.xlsx
  nfra_page_attachments_500/
    *.xls / *.xlsx / *.doc / *.docx / *.pdf
```

说明：

1. `qa/` 放原始题库或标注问答
2. `nfra_page_attachments_500/` 放监管附件原始文件
3. 原始大文件默认本地保留，不直接提交到 Git

### 解析结果

```text
data/parsed/
  docs/parsed_docs.jsonl
  tables/table_evidence.jsonl
  tables/parsed_tables.jsonl          # 可选完整单元格归档
  meta/doc_meta.jsonl
  meta/generated_manifest.jsonl
```

说明：

1. `docs/` 存放 Word/PDF/Doc 正文块解析结果
2. `tables/table_evidence.jsonl` 是模块2使用的表摘要和行级证据
3. `tables/parsed_tables.jsonl` 是可选完整单元格审计归档
4. `meta/` 存放文件级元信息和自动生成的 manifest

Git 提交规则：

1. `data/parsed/docs/parsed_docs.jsonl`、`data/parsed/meta/doc_meta.jsonl`、`data/parsed/meta/generated_manifest.jsonl` 体积可接受，随仓库提交。
2. `tables/table_evidence.jsonl` 和 `tables/parsed_tables.jsonl` 体积较大，由 `.gitignore` 忽略。
3. 被忽略的大文件仍必须放在上述标准路径，所有模块只使用这一套目录契约。
4. `data/samples/` 仅作为单元测试夹具，不是模块1向模块2的交付路径。

### 处理结果

```text
data/processed/
  chunks/
  kb/
  eval_ready/
```

说明：

1. `chunks/` 存放条款 chunk、表格 chunk
2. `kb/` 存放知识库、metadata db、索引映射
3. `eval_ready/` 存放清洗后的评测数据

## 当前接入状态

当前本地已完成：

1. 500 份监管附件接入到 `data/raw/nfra_page_attachments_500/`
2. `QA数据.xlsx` 仍在赛题原始目录；需要评测时复制到 `data/raw/qa/`
3. `parsed/` 和 `processed/` 子目录已经建立完成
4. 模块1使用独立 MySQL 数据库 `finance_innovation_rag` 保存规范化结果
5. 模块1与模块2统一使用 `data/parsed/`，不设置第二套样例运行配置

## 团队协作约定

1. 模块 1 只写 `data/parsed/`，原始附件只放在 `data/raw/`
2. 模块 2 只写 `data/processed/`
3. 评测模块优先消费 `data/processed/eval_ready/`
4. 不要跨模块直接写彼此目录
5. 大文件可通过本地复制方式放回约定目录，但代码和配置中的路径不改变
