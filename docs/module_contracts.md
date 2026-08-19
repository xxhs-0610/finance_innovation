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

模块3接收用户问题，通过查询理解、候选召回、融合排序和证据选择，输出可供模块4生成答案的证据包。

模块3项目介绍、完整运行说明和模块4验收清单见 `docs/模块3项目介绍与模块4对接.md`。

### 查询分析格式

```json
{
  "question": "2025年三季度商业银行资本充足率是多少？",
  "query_type": "table_lookup",
  "keywords": ["商业银行", "资本充足率", "2025年三季度"],
  "filters": {
    "publish_date": "2025"
  },
  "entities": {
    "institution": "商业银行",
    "metric": "资本充足率",
    "period": "2025年三季度",
    "normalized_period": "2025Q3"
  },
  "preferred_chunk_type": "table"
}
```

`query_type` 当前支持：

- `regulation_fact`：监管制度事实题
- `clause_threshold`：条款、比例和阈值题
- `business_procedure`：业务流程题
- `table_lookup`：统计表格取数题
- `cross_document`：跨文件比较或判断题
- `ambiguous`：信息不足、需要澄清的问题
- `unsupported`：知识库范围外的问题，由后续可信校验阶段结合召回结果判定

### 检索响应格式

```json
{
  "query": "2025年三季度商业银行资本充足率是多少？",
  "analysis": {
    "question": "2025年三季度商业银行资本充足率是多少？",
    "query_type": "table_lookup",
    "keywords": ["商业银行", "资本充足率", "2025年三季度"],
    "filters": {"publish_date": "2025"},
    "entities": {
      "institution": "商业银行",
      "metric": "资本充足率",
      "period": "2025年三季度",
      "normalized_period": "2025Q3"
    },
    "preferred_chunk_type": "table"
  },
  "evidence": [
    {
      "chunk_id": "doc101_table_0003",
      "chunk_type": "table",
      "score": 0.01639344262295082,
      "text": "表名：商业银行主要监管指标 指标：资本充足率 期间：2025Q3 单位：% 数值：12.35",
      "source": {
        "doc_id": "doc101",
        "title": "监管统计指标样例",
        "issuer": "国家金融监督管理总局",
        "publish_date": "2025-09-30",
        "source_url": "https://example.com/doc101",
        "local_path": "data/raw/doc101.xlsx",
        "section_path": [],
        "clause_no": "",
        "sheet_name": "资本监管指标",
        "table_name": "商业银行主要监管指标",
        "cell_ref": "B4"
      },
      "metadata": {
        "metric_name": "资本充足率",
        "period": "2025Q3",
        "unit": "%",
        "value": "12.35",
        "filtering": {
          "applied_filters": {"publish_date": "2025"},
          "relaxed_filters": [],
          "attempt": "strict"
        }
      }
    }
  ],
  "diagnostics": {
    "routing": {
      "query_type": "table_lookup",
      "skipped_retrievers": []
    },
    "retrievers": {
      "bm25": {"status": "ok", "candidate_count": 3}
    },
    "reranker": {"status": "disabled"},
    "failures": []
  }
}
```

模块4推荐调用 `retrieve(question)` 获取完整检索响应；该响应包含 `status`、`module4_guidance`、查询分析、证据和诊断信息。旧代码仍可通过 `retrieve_evidence(question)` 获取只包含 `evidence` 的兼容列表，但会丢失“需澄清/拒答/降级”状态，不应作为新交接链路的唯一接口。

### 模块4必须处理的响应状态

| `status` | 模块4动作 | 是否允许生成确定性答案 |
|---|---|---|
| `answerable` | 基于证据生成答案，并逐项保留引用 | 是 |
| `degraded` | 可以生成，但必须提示召回通道或重排序器降级 | 是，带风险提示 |
| `needs_clarification` | 询问 `module4_guidance.clarification_question` | 否 |
| `no_evidence` | 拒答或提示补充条件，不得猜测 | 否 |

`module4_guidance` 至少包含：

```json
{
  "action": "answer | answer_with_warning | clarify | refuse",
  "may_generate_answer": true,
  "require_citations": true,
  "preserve_numeric_source_value": true
}
```

当 `action=clarify` 时，模块4应优先展示 `clarification_question`；当 `action=refuse` 时不得根据向量相似度自行补写数值。

当表格同一期间命中多个有效数值列且用户未指定统计口径时，模块3返回 `missing_entities=["table_dimension"]`，并可通过 `clarification_options` 提供可选列名。模块4不得默认选择第一列。用户明确某一银行档次的阈值问题，证据必须明确包含同一档次；没有档次范围或档次冲突的候选会被模块3过滤。

`diagnostics` 用于记录各召回通道和重排序器的运行状态。某个可选向量后端或重排序器失败时，模块3继续使用其余成功候选，并在 `failures` 中记录 `stage`、`component` 和 `error_type`；不得把异常信息或敏感配置直接返回给调用方。

### 题型路由规则

- `table_lookup`：启用通用关键词/向量召回和表格专用检索
- `regulation_fact`、`clause_threshold`、`business_procedure`：优先检索条款 chunk，不调用只支持表格题的检索器
- `cross_document`：允许同时召回条款和表格，由后续融合与重排序决定证据
- `ambiguous`、`unsupported`：不执行知识库召回，交由模块4或前端请求用户澄清

没有参与当前题型的检索器在 `diagnostics.retrievers` 中记为 `skipped`，并加入 `diagnostics.routing.skipped_retrievers`。

### 查询实体补充约定

模块3可在 `entities` 中继续提供以下可选字段，不要求每个问题都存在：

- `document`：书名号中的文件名称
- `document_number`：监管文件文号
- `clause_no`：条款号
- `date`：完整日期原文
- `period`：年份、季度或报告期原文
- `normalized_period`：标准化季度，如 `2025Q3`
- `start_year` / `end_year`：日期区间起止年份
- `operator`：`minimum`、`maximum`、`not_less_than`、`not_more_than`、`year_on_year`、`month_on_month` 或 `compare`
- `value`：问题中出现的数字、百分比或金额

### 元数据过滤放宽约定

模块3默认使用全部解析出的过滤条件进行严格召回。若严格召回为空，可以删除容易与“适用年份”混淆的 `publish_date` 条件后重试，但不得自动删除用户明确指定的 `title` 或 `issuer`。

发生重试时，每条证据的 `metadata.filtering` 必须记录：

- `applied_filters`：本次实际使用的过滤条件
- `relaxed_filters`：相较严格条件被删除的字段列表
- `attempt`：`strict` 或 `relaxed_publish_date`

这样模块4能够识别证据是否来自放宽检索，必要时提示用户确认适用日期。

### 查询实体后置过滤

模块2当前数据库只原生支持部分元数据条件，因此模块3在候选召回后继续执行以下强约束：

- 查询包含 `clause_no` 时，条款候选的 `source.clause_no` 必须精确匹配
- 查询包含 `start_year` / `end_year` 时：
  - 条款候选按 `source.publish_date` 的年份判断
  - 表格候选优先按 `metadata.period` 或 `metadata.col_header` 中的年份判断

这些强约束不得自动放宽。保留的候选在 `metadata.entity_filtering` 中记录实际检查字段；若全部候选被过滤，模块3返回空证据，由后续模块请求澄清或调整问题。

对 `clause_threshold` 问题，若用户明确 `bank_tier`，候选条款必须能够从标题、章节路径或正文证明相同档次；无档次标签的通用条款不能替代指定档次证据。

监管文号只有在模块2稳定提供 `document_number` 字段后才能作为强过滤条件。在此之前，模块3仅将文号加入关键词检索，不声称完成了文号精确过滤。

## 模块2向量索引 -> 模块3向量检索

向量索引的构建、持久化、版本和 `chunk_id` 映射归模块2负责；模块3只通过统一向量后端读取候选，不在查询链路中重建索引。

向量后端应实现以下语义接口：

```python
search(
    query: str,
    *,
    top_k: int,
    chunk_type: str | None,
    filters: dict[str, str],
) -> list[SearchResult]
```

约束如下：

- 返回对象必须使用 `app.schemas.chunk_schema.SearchResult`
- `chunk_id` 必须与模块2的条款、表格 chunk 完全一致
- `score` 必须满足数值越大表示语义越相关
- 必须保留完整 `source` 与 `metadata`
- 应支持 `doc_id`、`title`、`issuer`、`publish_date` 过滤，或在适配层实现等价过滤
- 索引配置应记录 embedding 模型名称、维度、相似度类型和索引版本

模块3的 `VectorRetriever` 与 BM25 使用相同的发布日期放宽规则，并将实际过滤条件写入 `metadata.filtering`。

### 仍待模块2补充的可选检索字段

为支持比赛要求的版本、时效和条款级可信引用，模块2后续应在统一 chunk/source schema 中确认以下可选字段：

```json
{
  "document_number": "金规〔2023〕4号",
  "document_version": "2023-11-01发布版",
  "effective_date": "2024-01-01",
  "expiry_date": null,
  "parent_chunk_id": "doc001_clause_0010",
  "chunk_order": 10,
  "table_granularity": "table_cell_group"
}
```

字段未提供前，模块3不得通过正文猜测正式文号、文件版本、生效状态或相邻条款关系。

## 模块2表格chunk -> 模块3表格检索

模块3的表格专用检索器读取模块2现有 `KnowledgeBaseReader`，先召回 `chunk_type=table` 候选，再按照结构字段进行二次排序。表格 chunk 的 `metadata` 支持单值结构和模块1正式行级证据结构：

- `table_name`
- `metric_name`
- `period`
- `unit`
- `value`，或 `values[]` 中的多个表头、数值和单元格引用
- `row_header`
- `col_header`
- `cell_ref`

`source.cell_ref` 可以对应单元格，也可以对应正式行级证据的 `cell_range`。表格二次排序优先使用指标精确匹配、标准化报告期匹配和指定文件匹配，并在 `metadata.table_matching` 中记录命中字段与原始BM25分数。结构字段只用于排序和证据诊断，不得改写原始表格数值。

## 模块3重排序接口

重排序器接收用户问题和融合后的候选证据文本，返回与输入一一对应的相关性分数。当前代码通过可注入的 pair scorer 适配 Cross-Encoder 或其他重排序服务，不绑定具体模型依赖。

重排序后的证据在 `metadata.reranking` 中记录：

```json
{
  "reranker": "example-cross-encoder",
  "score": 0.91,
  "previous_score": 0.0325
}
```

其中 `previous_score` 是 RRF 融合分数，`score` 是重排序分数。

## 模块3证据质量诊断

证据选择阶段不补写或猜测来源字段，只在 `metadata.evidence_quality` 中标记来源是否足以引用：

```json
{
  "complete": true,
  "missing_fields": []
}
```

条款证据至少检查 `doc_id`、`title`、来源定位以及条款/章节定位；表格证据还要检查表名、单元格、指标、期间和数值。诊断字段供模块4决定是否正常回答、降级提示或拒答。

### 最小充分证据规则

- 单指标表格取数题：若候选同时满足指标精确匹配、指定报告期匹配和来源完整，只返回排名最高的一条单元格证据
- 表格同一期间存在多个有效数值列且缺少列维度时：返回 `needs_clarification`，不默认选择第一列
- 单指标阈值题：若候选包含目标指标、数字/比例和完整条款来源，只返回排名最高的一条条款证据
- 业务流程题：允许保留多个连续或互补条款，不应用单证据提前停止
- 跨文件题：先保证不同 `doc_id` 的高排名证据各有一条，再用剩余候选补足 Top-K
- 无法确认直接支撑时：保留正常去重后的 Top-K，不强行缩减证据

RRF融合遇到相同 `chunk_id` 时必须合并各召回通道附加的非冲突元数据，例如 `table_matching`，并在 `metadata.retrieval.sources` 中保留每路原始排名和分数。

### 模块4接收证据的最小字段

模块4直接接收模块3的证据列表。每条证据至少必须包含：

- `chunk_id`
- `chunk_type`
- `text`
- `source.doc_id`

建议同时提供 `score`、完整 `source` 和表格 `metadata`，用于置信度计算、关键字段校验和数字回溯。若模块3返回完整检索响应，模块4必须优先遵循其 `status` 和 `module4_guidance`，而不是仅根据相似度自行生成答案。

## 模块4 -> 模块5

模块4正式调用模块3的完整响应，并通过 `app.generation.answer_generator.generate_answer(question, retrieval_response)` 输出结构化回答。直接传入证据列表仅作为旧代码兼容方式：

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
- `degraded`：答案通过校验，但一个或多个检索通道发生降级
- `needs_clarification`：问题缺少指标、期间、银行档次或统计口径，不生成确定性答案
- `no_evidence`：模块3没有找到可用于回答的可靠证据
- `refused`：证据不足、明显不相关或生成内容未通过校验

为兼容当前前端，`status`、`answer`、`evidence`、`risk_tips` 四个字段始终存在。模块4还会透传 `retrieval_status`、`module4_guidance` 和 `diagnostics`；需要澄清时同时提供 `clarification_question`，存在候选口径时提供 `clarification_options`。模块5可进一步展示 `confidence`、`citations` 和 `verification`。

