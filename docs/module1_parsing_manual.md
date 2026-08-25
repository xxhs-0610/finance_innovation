# 模块1文档解析使用手册

本模块将银行业监管 Word、PDF、Excel 附件解析为可追溯的正文块和表格单元，写入独立 MySQL 数据库，并导出模块2使用的 JSONL。

## 1. 目录与数据流

```text
data/raw/nfra_page_attachments_500/       原始附件
data/parsed/docs/parsed_docs.jsonl        正文块
data/parsed/tables/table_evidence.jsonl   模块2使用的表格检索证据
data/parsed/tables/parsed_tables.jsonl    可选完整单元格归档
data/parsed/meta/doc_meta.jsonl           文件元数据
data/parsed/meta/generated_manifest.jsonl 自动生成的 manifest
reports/module1_parsing_report.md         质量报告
configs/parsing.json                      非敏感配置
```

MySQL 数据库固定使用 `finance_innovation_rag`。`finance_risk` 和 `finance_risk_data` 不参与本模块读写。

## 2. 环境准备

安装基础依赖：

```powershell
pip install -r requirements.txt
```

旧版 `.doc` 的处理顺序：

1. 使用 PATH 中的 LibreOffice/soffice 无界面转换。
2. Windows 安装 Microsoft Word 时使用 Word COM 后备。
3. 两种方式都不可用时记录 `DOC_CONVERTER_UNAVAILABLE`，不会静默丢弃文件。

PDF 图片页 OCR 需要：

```powershell
pip install rapidocr_onnxruntime PyMuPDF
```

没有 OCR 依赖时，普通文本 PDF 仍可解析；低文本图片页会记录可重试警告。

## 3. 数据库配置

基础连接参数放在 `configs/parsing.json`。密码只能通过环境变量提供：

```powershell
$env:RAG_DB_HOST="127.0.0.1"
$env:RAG_DB_PORT="3306"
$env:RAG_DB_USER="root"
$env:RAG_DB_PASSWORD="你的本地密码"
$env:RAG_DB_NAME="finance_innovation_rag"
```

可先检查环境，不会创建数据库：

```powershell
python scripts/parse_documents.py check
```

创建数据库和表：

```powershell
python scripts/parse_documents.py init-db
```

该命令使用 `CREATE DATABASE/TABLE IF NOT EXISTS` 和版本迁移记录，不会修改两个既有业务库。

## 4. 接入原始数据

如果附件仍在比赛根目录，运行：

```powershell
python scripts/parse_documents.py sync-raw
```

命令会复制到 `data/raw/nfra_page_attachments_500/`，不会删除或移动原始文件。也可指定其他来源：

```powershell
python scripts/parse_documents.py sync-raw --source "D:\dataset\attachments"
```

生成文件哈希、稳定 `doc_id` 和 manifest：

```powershell
python scripts/parse_documents.py inventory
```

附件编号生成类似 `nfra_att_001` 的 `doc_id`；无编号文件使用 SHA-256 前缀。

## 5. 执行解析

增量解析全部待处理或发生变化的文件：

```powershell
python scripts/parse_documents.py parse --all
```

常用控制方式：

```powershell
# 只解析一种格式
python scripts/parse_documents.py parse --file-type pdf

# 解析指定文件
python scripts/parse_documents.py parse --doc-id nfra_att_397

# 重新解析所有文件
python scripts/parse_documents.py parse --force

# 只重试失败或部分成功文件
python scripts/parse_documents.py parse --retry-failed

# 小批量验证
python scripts/parse_documents.py parse --limit 10
```

每个文档单独使用事务。失败时该文档本次产生的数据整体回滚，其他文档不受影响。重复解析会将旧记录标记为非活动并 upsert 当前记录，不直接删除历史行。

## 6. 导出和模块2衔接

```powershell
python scripts/parse_documents.py export-jsonl
```

默认导出文件元数据、正文块和检索级表格证据，不重复生成约 1 GB 的完整单元格归档。如确实需要审计快照：

```powershell
python scripts/parse_documents.py export-jsonl --include-cell-archive
```

输出映射：

| MySQL 数据 | JSONL |
|---|---|
| `rag_documents` | `data/parsed/meta/doc_meta.jsonl` |
| `rag_documents + rag_document_blocks` | `data/parsed/docs/parsed_docs.jsonl` |
| 表摘要 + 单元格按行分段 | `data/parsed/tables/table_evidence.jsonl` |
| 完整单元格（可选） | `data/parsed/tables/parsed_tables.jsonl` |

随后构建模块2知识库：

```powershell
python scripts/build_kb.py
```

模块2默认读取 `table_evidence.jsonl`。每条证据最多包含同一行的 20 个单元格；大型矩阵会拆成多个行分段，避免逐单元格建索引。所有值仍保留单元格坐标，必要时可回溯 MySQL 和原文件。

所有模块统一使用 `data/parsed/`。其中 `parsed_docs.jsonl` 和元数据文件可以提交 Git；体积较大的 `table_evidence.jsonl` 与 `parsed_tables.jsonl` 保持忽略，由团队成员本地放回约定目录。模块2不使用第二套样例输入路径。

## 7. 数据库表

| 表 | 作用 |
|---|---|
| `rag_schema_migrations` | 数据库结构版本 |
| `rag_parse_runs` | 每次解析运行与统计 |
| `rag_documents` | 文件元数据和解析状态 |
| `rag_document_blocks` | 标题、条款、段落及页码 |
| `rag_tables` | sheet/PDF/Word 表格元数据 |
| `rag_table_cells` | 单元格、表头、指标、期间、单位、公式和值 |
| `rag_parse_issues` | 警告、错误和重试信息 |

常用查询：

```sql
-- 文件状态
SELECT file_type, parse_status, COUNT(*)
FROM rag_documents
GROUP BY file_type, parse_status;

-- 查询条款及原文定位
SELECT d.title, b.section_path, b.clause_no, b.text, b.page_no
FROM rag_document_blocks b
JOIN rag_documents d ON d.doc_id = b.doc_id
WHERE b.is_active = 1 AND b.clause_no = '第二十条';

-- 查询表格指标
SELECT d.title, t.sheet_name, c.metric_name, c.period,
       c.unit, c.display_value, c.cell_ref
FROM rag_table_cells c
JOIN rag_tables t ON t.table_id = c.table_id
JOIN rag_documents d ON d.doc_id = c.doc_id
WHERE c.is_active = 1 AND c.metric_name LIKE '%资本充足率%';

-- 查看可重试问题
SELECT doc_id, stage, error_code, message
FROM rag_parse_issues
WHERE retryable = 1
ORDER BY issue_id DESC;
```

## 8. 质量报告与核验

```powershell
python scripts/parse_documents.py report
```

报告包含文件格式、解析状态、正文块、表格、活动单元格和问题文件统计。

溯源核验方式：

- Word：查看 `source_locator.sequence_no` 和样式。
- PDF：查看 `page_no`、行号和 `bbox`。
- Excel：查看 `sheet_name` 和 `cell_ref`。
- 原始文件：查看 `rag_documents.local_path` 与 SHA-256。

## 9. 常见问题

### MySQL 无法连接

先运行 `check`，确认端口、账号和密码。不要把密码写入 `configs/parsing.json`。

### `.doc` 解析失败

安装 LibreOffice，或在 Windows 安装 Microsoft Word 和 `pywin32`，再运行 `parse --retry-failed`。

### Excel 公式没有缓存值

数据库仍会保留 `formula` 和 `raw_value`。若 `display_value` 为空，可先用 Excel/LibreOffice 重新计算并保存原文件，再重试。

### PDF 图片页无文本

安装 RapidOCR 和 PyMuPDF，执行 `parse --retry-failed`。纯图片但没有可识别文字的页面会保留问题记录。

### 超大 Excel 耗时较长

模块按 1000 个单元格批量 upsert。百万单元格模板首次写入约需数分钟；已有百万行的强制重跑可能需要 10—20 分钟，但日常增量运行会自动跳过未变化文件，也不会一次性把全部记录保存在 Python 列表中。

## 10. 模块1交付检查清单

- `rag_documents` 中所有源文件都有状态。
- `generated_manifest.jsonl` 数量与原始附件一致。
- 正文证据包含章节或页码定位。
- 表格证据包含 sheet、行列表头和 `cell_ref`。
- `parsed_docs.jsonl`、`table_evidence.jsonl` 和 `doc_meta.jsonl` 已生成且路径符合模块契约。
- `python scripts/build_kb.py` 能读取正文和表格 JSONL。
- 质量报告中的失败文件已处理或给出明确说明。
