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

