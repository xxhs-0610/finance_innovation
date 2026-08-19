# 模块4：生成与可信控制

模块4接收模块3返回的 Top-K 证据包，输出模块5可以直接展示或序列化的结构化回答。

## 已实现能力

1. 证据标准化并分配 `E1`、`E2` 等引用编号
2. 无外部模型时的保守抽取式回答
3. 可注入大模型生成函数的统一入口
4. 金额、比例、日期、文号、机构名和规范词校验
5. 无证据、证据明显不相关、关键字段无法核验时拒答
6. 置信度、风险提示和校验明细输出

## 调用方式

```python
from app.generation.answer_generator import generate_answer

result = generate_answer(question, evidence)
```

接入大模型时传入一个签名为 `generator(question, normalized_evidence) -> str` 的函数：

```python
result = generate_answer(question, evidence, generator=my_llm_generator)
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
