# 模块2实施计划：知识库与索引

模块2负责把模块1的结构化解析结果变成可检索、可回溯、可评测的知识底座。

## MVP 范围

当前版本先完成：

1. 条款 chunk 切分
2. 表格 chunk 切分
3. 统一 chunk schema
4. `metadata.db` 元数据入库
5. SQLite FTS5 关键词检索
6. 可供模块3调用的 `KnowledgeBaseReader`

## 模块1输入

模块2统一通过 `configs/default.json` 消费：

- `data/parsed/docs/parsed_docs.jsonl`：制度正文段落和条款
- `data/parsed/tables/table_evidence.jsonl`：表摘要和行级表格证据

模块2不直接消费完整单元格归档 `parsed_tables.jsonl`，避免将百万单元格逐个建立索引。

```powershell
python scripts/build_kb.py
```

`parsed_docs.jsonl` 可提交 Git；体积较大的 `table_evidence.jsonl` 由成员本地放入标准目录。模块2不提供第二套输入路径或样例运行模式。

暂不强依赖：

- FAISS
- embedding 模型
- reranker

这些能力后续可以作为增强项接入，不影响当前接口。

## 后续增强

1. 增加中文分词或字符 ngram，提高短词召回
2. 接入 sentence-transformers 生成 embedding
3. 建 FAISS 向量索引
4. 增加 chunk 质量审计脚本
5. 增加表格结构检索，包括表头、期间、单位、指标名过滤

