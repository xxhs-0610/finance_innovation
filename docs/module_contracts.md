# 模块接口契约

这份文档用于约定 6 个模块之间的数据边界。团队成员新增字段时，先更新这里，再改代码。

## 模块1 -> 模块2

模块1输出结构化解析结果。

### `data/parsed/parsed_docs.jsonl`

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

### `data/parsed/parsed_tables.jsonl`

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

### `data/parsed/doc_meta.jsonl`

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

