# 模块4：生成与可信控制

模块4正式接收模块3返回的完整 `RetrievalResponse`，根据检索状态决定回答、降级提示、澄清或拒答，并输出模块5可以直接展示或序列化的结构化结果。直接传入 Top-K 证据列表的方式仅用于旧代码兼容。

## 已实现能力

1. 证据标准化并分配 `E1`、`E2` 等引用编号
2. 无外部模型时的保守抽取式回答
3. 可注入大模型生成函数的统一入口
4. 金额、比例、日期、文号、机构名和规范词校验
5. 无证据、证据明显不相关、关键字段无法核验时拒答
6. 置信度、风险提示和校验明细输出
7. 处理 `answerable`、`degraded`、`needs_clarification` 和 `no_evidence` 状态
8. 保留模块3的 `module4_guidance`、`diagnostics` 和澄清选项
9. 对比例类表格原值进行确定性百分比换算，并同时保留原值和换算说明
10. 对 `evidence_quality.complete=false` 的证据拒绝生成确定性答案

## 调用方式

```python
from app.generation.answer_generator import generate_answer
from app.retrieval.hybrid_retriever import retrieve

retrieval_response = retrieve(question)
result = generate_answer(question, retrieval_response)
```

兼容旧调用时仍可传入证据列表，但会缺少模块3的澄清、拒答和降级状态：

```python
result = generate_answer(question, evidence)
```

接入大模型时传入一个签名为 `generator(question, normalized_evidence) -> str` 的函数：

```python
result = generate_answer(
    question,
    retrieval_response,
    generator=my_llm_generator,
)
```

模型提示词可以通过 `build_generation_prompt(question, evidence)` 构造。无论模型返回什么文本，最终都要经过 `verify_answer()`；证据外关键字段会触发拒答。

## 输出字段

```json
{
  "status": "answered",
  "answer": "结论…… [E1]",
  "evidence": [],
  "risk_tips": [],
  "confidence": 0.86,
  "citations": ["E1"],
  "verification": {
    "passed": true,
    "unsupported_claims": []
  }
}
```

`status` 可能为：

- `answered`：生成和校验均通过
- `degraded`：生成和校验通过，但模块3部分检索通道降级
- `needs_clarification`：缺少指标、银行档次或表格统计口径
- `no_evidence`：模块3没有找到可靠证据
- `refused`：模块4本地充分性检查或生成后校验失败
