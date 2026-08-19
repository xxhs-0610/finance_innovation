# 模块接口契约

这份文档用于约定 6 个模块之间的数据边界。团队成员新增字段时，先更新这里，再改代码。

## 模块1 -> 模块2

模块1输出结构化解析结果。

所有成员统一使用 `data/parsed/` 作为模块交付路径，不设置第二套运行配置。体积可接受的正文和元数据文件提交 Git；超大表格文件被忽略后，由成员本地放回相同标准路径。

### `data/parsed/docs/parsed_docs.jsonl`

每行表示一个制度正文片段，至少包含：

```json
{
  "doc_id": "doc001",
  "title": "商业银行资本管理办法",
  "issuer": "国家金融监督管理总局",
  "publish_date": "2023-11-01",
  "source_url": "https://example.com/doc001",
  "local_path": "data/raw/doc001.pdf",
  "section_path": ["第一章 总则", "第二条"],
  "clause_no": "第二条",
  "text": "商业银行应当按照本办法计量资本充足率。"
}
```

### `data/parsed/tables/table_evidence.jsonl`（模块2正式输入）

每行表示表摘要，或一个可检索、可回溯的表格行分段：

```json
{
  "evidence_id": "nfra_att_032_sheet_001_row_000004_part_001",
  "record_type": "table_row",
  "doc_id": "nfra_att_032",
  "title": "2025年9月全国各地区原保险保费收入情况表",
  "sheet_name": "各地区数据（月度）",
  "table_name": "2025年9月全国各地区原保险保费收入情况表",
  "metric_name": "全国",
  "period": "2025-09",
  "unit": "亿元",
  "cell_range": "B4:G4",
  "values": [
    {"header": "合计", "value": "52145.77", "cell_ref": "C4"},
    {"header": "寿险", "value": "31707.75", "cell_ref": "E4"}
  ],
  "retrieval_text": "2025年9月全国各地区原保险保费收入情况表 | 全国 | 合计=52145.77；寿险=31707.75 | 单位：亿元"
}
```

`record_type` 包含：

- `table_summary`：表名、sheet、期间、单位、范围和行列规模
- `table_row`：最多 20 个单元格组成的行级证据，保留每个值的 `cell_ref`

### `data/parsed/tables/parsed_tables.jsonl`（可选审计归档）

每行表示一个表格区域、指标行或单元格组，至少包含：

```json
{
  "doc_id": "doc101",
  "title": "监管统计附件",
  "sheet_name": "资本监管指标",
  "table_name": "商业银行主要监管指标",
  "metric_name": "资本充足率",
  "period": "2025Q3",
  "unit": "%",
  "value": "12.35",
  "row_header": "资本充足率",
  "col_header": "2025年三季度",
  "cell_ref": "B3",
  "source_url": "https://example.com/table101",
  "local_path": "data/raw/table101.xlsx"
}
```

该文件保留完整单元格，适合核验和重新生成证据，不作为模块2默认输入。完整数据的唯一事实源是 MySQL；需要时使用 `export-jsonl --include-cell-archive` 重新导出。

### `data/parsed/meta/doc_meta.jsonl`

每行表示一个源文件元数据，建议包含：

```json
{
  "doc_id": "doc001",
  "title": "商业银行资本管理办法",
  "issuer": "国家金融监督管理总局",
  "publish_date": "2023-11-01",
  "file_type": "pdf",
  "source_url": "https://example.com/doc001",
  "local_path": "data/raw/doc001.pdf",
  "sha256": "..."
}
```

## 模块2 -> 模块3

模块2输出可检索知识库和统一证据字段。

### `data/processed/clause_chunks.jsonl`

条款 chunk，一条法规条款优先对应一个 chunk。若条款太长，可拆成多个 chunk，但必须保留同一个 `clause_no` 和 `section_path`。

### `data/processed/table_chunks.jsonl`

表格 chunk，建议保留两类粒度：

- `table_region`：整表或表格区域摘要
- `table_cell_group`：指标行、单元格组或可回答取数题的最小单元

### 证据返回格式

模块3检索时应拿到如下结构：

```json
{
  "chunk_id": "doc001_clause_0001",
  "chunk_type": "clause",
  "score": 1.0,
  "text": "商业银行应当按照本办法计量资本充足率。",
  "source": {
    "doc_id": "doc001",
    "title": "商业银行资本管理办法",
    "issuer": "国家金融监督管理总局",
    "publish_date": "2023-11-01",
    "section_path": ["第一章 总则", "第二条"],
    "clause_no": "第二条",
    "source_url": "https://example.com/doc001",
    "local_path": "data/raw/doc001.pdf"
  }
}
```

## 模块3 -> 模块4

模块4直接接收上述证据列表。每条证据必须至少包含：

- `chunk_id`
- `chunk_type`
- `text`
- `source.doc_id`

建议同时提供 `score`、完整 `source` 和表格 `metadata`，用于置信度计算与数字回溯。

## 模块4 -> 模块5

模块4通过 `app.generation.answer_generator.generate_answer(question, evidence)` 输出：

```json
{
  "status": "answered",
  "answer": "商业银行资本充足率不得低于8%。[E1]",
  "evidence": [],
  "risk_tips": [],
  "confidence": 0.9,
  "citations": ["E1"],
  "verification": {
    "passed": true,
    "issues": [],
    "unsupported_claims": []
  }
}
```

`status` 当前包含：

- `answered`：证据充分且关键字段校验通过
- `refused`：证据不足、明显不相关或生成内容未通过校验

为兼容当前前端，`status`、`answer`、`evidence`、`risk_tips` 四个字段始终存在。模块5可进一步展示 `confidence`、`citations` 和 `verification`。

