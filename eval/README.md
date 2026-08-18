# 模块2/模块6：检索评测与实验

当前先提供模块2可直接使用的检索评测闭环：

- `retrieval_eval_set.jsonl`：种子评测问题集
- `run_retrieval_eval.py`：自动跑检索、计算 Hit@1、Hit@K、MRR

运行真实知识库评测：

```powershell
python eval/run_retrieval_eval.py `
  --db-path data/processed/kb_rebuild/metadata.db `
  --top-k 5 `
  --output reports/retrieval_eval_report.jsonl
```

如果想看未优化的原始 BM25/FTS 效果：

```powershell
python eval/run_retrieval_eval.py `
  --db-path data/processed/kb_rebuild/metadata.db `
  --top-k 5 `
  --no-rerank
```

后续可以继续扩展五类问题：

1. 监管制度事实题
2. 条款/阈值题
3. 业务流程题
4. 统计表格取数题
5. 跨文件场景判断题
