# 模块2：向量索引与混合检索使用说明

这份文档说明模块2新增的向量索引能力。模块2的职责不是生成最终答案，而是把模块1解析出的内容整理成“可检索、可回溯、可交给模块3调用”的知识库。

## 1. 输入文件

向量索引直接读取模块2已经生成好的 chunk 文件：

```text
data/processed/kb_rebuild/clause_chunks.jsonl
data/processed/kb_rebuild/table_chunks.jsonl
```

其中：

- `clause_chunks.jsonl`：制度条款类 chunk
- `table_chunks.jsonl`：统计报表/表格证据类 chunk

每条 chunk 至少需要包含：

```json
{
  "chunk_id": "...",
  "chunk_type": "clause 或 table",
  "doc_id": "...",
  "text": "...",
  "retrieval_text": "..."
}
```

向量索引优先使用 `retrieval_text` 生成 embedding；如果没有该字段，再使用 `text`。

## 2. 输出文件

构建完成后会生成：

```text
indexes/kb_rebuild/embeddings.npy
indexes/kb_rebuild/faiss.index
indexes/kb_rebuild/chunk_id_map.json
indexes/kb_rebuild/vector_meta.json
```

这些文件的作用：

| 文件 | 作用 |
|---|---|
| `embeddings.npy` | 保存所有 chunk 的 embedding 向量 |
| `faiss.index` | FAISS 向量索引，用于语义检索 |
| `chunk_id_map.json` | 保存 FAISS 向量序号和 `chunk_id` 的对应关系 |
| `vector_meta.json` | 保存模型名、向量维度、chunk 数量等索引信息 |

注意：这些文件通常比较大，默认不建议提交到 GitHub。队友拉代码后，可以本地重新生成；或者团队用网盘/共享盘传索引产物。

## 3. 构建向量索引

在项目根目录运行：

```powershell
python scripts/build_vector_index.py `
  --processed-dir data/processed/kb_rebuild `
  --indexes-dir indexes/kb_rebuild `
  --embedding-backend sentence-transformers `
  --model-name BAAI/bge-small-zh-v1.5 `
  --batch-size 64
```

如果电脑内存较小，可以把 batch 调小：

```powershell
python scripts/build_vector_index.py `
  --processed-dir data/processed/kb_rebuild `
  --indexes-dir indexes/kb_rebuild `
  --batch-size 16
```

如果只是测试脚本是否能跑，可以先只建前 200 条：

```powershell
python scripts/build_vector_index.py `
  --processed-dir data/processed/kb_rebuild `
  --indexes-dir indexes/kb_rebuild `
  --embedding-backend hashing `
  --limit 200
```

`hashing` 只是离线测试用，不是真正语义模型。正式比赛建议使用 `sentence-transformers`。

## 4. 向量检索

单独使用 FAISS 向量检索：

```powershell
python scripts/vector_search_kb.py "资本充足率" `
  --db-path data/processed/kb_rebuild/metadata.db `
  --index-dir indexes/kb_rebuild `
  --top-k 5
```

## 5. BM25 + FAISS 混合检索

使用统一搜索脚本：

```powershell
python scripts/search_kb.py "资本充足率" `
  --mode hybrid `
  --db-path data/processed/kb_rebuild/metadata.db `
  --index-dir indexes/kb_rebuild `
  --top-k 5
```

也可以只跑关键词检索：

```powershell
python scripts/search_kb.py "资本充足率" `
  --mode bm25 `
  --db-path data/processed/kb_rebuild/metadata.db
```

或者只跑向量检索：

```powershell
python scripts/search_kb.py "资本充足率" `
  --mode vector `
  --db-path data/processed/kb_rebuild/metadata.db `
  --index-dir indexes/kb_rebuild
```

## 6. 给模块3的调用方式

模块3可以直接调用：

```python
from app.indexing.index_reader import KnowledgeBaseReader

reader = KnowledgeBaseReader(
    "data/processed/kb_rebuild/metadata.db",
    vector_index_dir="indexes/kb_rebuild",
)

results = reader.hybrid_search("资本充足率", top_k=5)
```

返回结果结构统一为：

```json
{
  "chunk_id": "...",
  "chunk_type": "clause",
  "score": 1.0,
  "text": "...",
  "source": {
    "doc_id": "...",
    "title": "...",
    "issuer": "...",
    "publish_date": "...",
    "section_path": [],
    "clause_no": "",
    "sheet_name": "",
    "table_name": ""
  },
  "metadata": {
    "_retrieval": {
      "bm25_rank": 1,
      "vector_rank": 3,
      "fusion_score": 16.1
    }
  }
}
```

模块3只需要基于这些证据继续做查询理解、过滤、最终 rerank；模块4再根据证据生成可信答案。

## 7. 模块2和模块3的边界

模块2负责：

- 读取 chunk
- 生成 embedding
- 保存 `embeddings.npy`
- 建立 `faiss.index`
- 保存 `chunk_id_map.json`
- 提供向量检索接口
- 提供基础 BM25 + FAISS 混合检索能力

模块3负责：

- 理解用户问题
- 判断该查条款还是表格
- 提取年份、机构、指标、关键词
- 调用模块2提供的检索接口
- 合并候选证据并做最终业务排序

一句话：

```text
模块2把知识库建好；模块3决定用户这个问题应该怎么查。
```
