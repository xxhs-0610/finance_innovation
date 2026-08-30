# -*- coding: utf-8 -*-
"""Repair mojibake and translate the QA HTTP summary report."""
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "reports" / "qa_eval_http_full" / "QA_HTTP_summary.md"
dst = src.with_name("QA_HTTP_summary_中文.md")

def repair(text: str) -> str:
    # The report was once decoded as GBK after being written as UTF-8.
    # Reverse that transformation where it is lossless.
    try:
        candidate = text.encode("gbk").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    markers = ("锛", "鐨", "妫", "璇", "绱", "鎹", "鏁", "浠", "闂", "鍙", "搴", "瓒")
    return candidate if sum(text.count(m) for m in markers) > sum(candidate.count(m) for m in markers) else text

text = "\n".join(repair(line) for line in src.read_text(encoding="utf-8").splitlines())
replacements = {
    "# QA HTTP Evaluation Summary": "# QA HTTP 评测总结",
    "- Endpoint:": "- 测试接口：",
    "(same as frontend)": "（与前端相同）",
    "- Sent only question and options; gold answer/evidence were not sent.": "- 请求内容：仅发送问题和选项，未发送标准答案或标准证据。",
    "- DeepSeek remained enabled according to `.env`; local mode was not used.": "- DeepSeek：根据 `.env` 配置保持启用，未使用本地模式。",
    "- Total:": "- 总题数：",
    "- Answered:": "- 已回答：",
    "- Refused/request failed:": "- 拒答/请求失败：",
    "- Correct:": "- 回答正确：",
    "- Wrong among answered:": "- 已回答但答错：",
    "- Overall accuracy:": "- 总体准确率：",
    "- Answered accuracy:": "- 已回答准确率：",
    "## By type": "## 按题型统计",
    "|Type|Total|Answered|Refused|Correct|Wrong|": "|题型|总数|已回答|拒答|正确|答错|",
    "## Refused/request failed": "## 拒答/请求失败题",
    "|ID|Status|Reason|": "|题目 ID|状态|原因|",
    "## Wrong answered": "## 已回答但答错题",
    "|ID|Gold|Predicted|Status|": "|题目 ID|标准答案|系统答案|状态|",
    "refused": "拒答",
    "request_error": "请求失败",
    "answered": "已回答",
    "unspecified": "未说明",
    "none": "无",
    "unparsed": "未解析",
    "琛ㄦ牸鍙栨暟": "表格取数",
    "琛ㄦ牸姣旇緝": "表格比较",
    "琛ㄦ牸璁＄畻": "表格计算",
    "鍗曚簨瀹炴绱": "单事实检索",
    "澶氫簨瀹炴绱": "多事实检索",
}
for old, new in replacements.items():
    text = text.replace(old, new)
dst.write_text(text + "\n", encoding="utf-8")
print(dst)
