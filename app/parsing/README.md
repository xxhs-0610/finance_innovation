# 模块1：文档解析

模块1负责把原始 Word / PDF / Excel 解析到 MySQL，并导出结构化 JSONL。

请优先输出：

- `data/parsed/docs/parsed_docs.jsonl`
- `data/parsed/tables/table_evidence.jsonl`（模块2正式输入）
- `data/parsed/tables/parsed_tables.jsonl`（可选审计归档）
- `data/parsed/meta/doc_meta.jsonl`
- `data/parsed/meta/generated_manifest.jsonl`

字段契约见 `docs/module_contracts.md`。

完整命令、数据库表和故障处理见 `docs/module1_parsing_manual.md`。

