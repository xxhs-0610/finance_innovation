# -*- coding: utf-8 -*-
"""Batch QA evaluation through the frontend's HTTP endpoint."""
from __future__ import annotations
import argparse, csv, json, re, time
from pathlib import Path
from urllib import error, request
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("A", "B", "C", "D")

def cell(row, key):
    v = row.get(key)
    return "" if v is None else str(v).strip()

def build_query(row):
    q = cell(row, "question")
    opts = [f"{k}. {cell(row, 'option_' + k.lower())}" for k in KEYS if cell(row, 'option_' + k.lower())]
    if opts and not re.search(r"(?:^|\s)[ABCD][.、:：]", q):
        q += "\n" + "\n".join(opts)
    return q

def letters(v):
    return list(dict.fromkeys(re.findall(r"[ABCD]", str(v or "").upper())))

def load_rows(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    headers = [str(v).strip() if v is not None else "" for v in next(it)]
    rows = []
    for raw in it:
        row = {headers[i]: raw[i] if i < len(raw) else None for i in range(len(headers))}
        if cell(row, "question"):
            rows.append(row)
    return rows

def post_json(url, payload, timeout):
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except error.HTTPError as e:
        return {"status": "http_error", "error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}"}
    except Exception as e:
        return {"status": "request_error", "error": f"{type(e).__name__}: {e}"}

def predicted(result):
    ver = result.get("verification") if isinstance(result, dict) else None
    if isinstance(ver, dict):
        te = ver.get("table_execution")
        if isinstance(te, dict) and te.get("matched_option"):
            return letters(te["matched_option"])
        ov = ver.get("option_verification")
        if isinstance(ov, dict) and ov.get("selected_options"):
            return letters(ov["selected_options"])
    text = str(result.get("answer") or "")
    m = re.findall(r"(?:答案|选项|正确选项|选择)\s*[:：]?\s*([ABCD])(?:\b|[.。、])", text, re.I)
    if m:
        return list(dict.fromkeys(x.upper() for x in m))
    m = re.fullmatch(r"\s*([ABCD])\s*[.。、]?\s*", text, re.I)
    return [m.group(1).upper()] if m else []

def reason(result):
    for k in ("refusal_reason", "error_code"):
        if result.get(k):
            return str(result[k])
    v = result.get("verification")
    if isinstance(v, dict):
        if v.get("error_code"):
            return str(v["error_code"])
        if v.get("issues"):
            return "; ".join(map(str, v["issues"]))
    return str(result.get("error") or "")

def evaluate(rows, endpoint, limit, timeout):
    selected = rows[:limit] if limit and limit > 0 else rows
    out = []
    for i, row in enumerate(selected, 1):
        q = build_query(row)
        t = time.perf_counter()
        resp = post_json(endpoint, {"question": q, "top_k": 5}, timeout)
        ms = int((time.perf_counter() - t) * 1000)
        gold = letters(row.get("answer")) or letters(row.get("answer_text"))
        pred = predicted(resp)
        status = str(resp.get("status") or "unknown")
        refused = status not in {"answered", "success", "degraded"}
        accurate = bool(gold) and pred == gold and not refused
        item = {"id": cell(row, "id") or f"row_{i:03d}", "qa_type": cell(row, "qa_type"), "question": cell(row, "question"), "gold_answer": gold, "predicted_answer": pred, "status": status, "refused": refused, "accurate": accurate, "refusal_reason": reason(resp), "source_title": cell(row, "source_title"), "system_answer": resp.get("answer", ""), "elapsed_ms": ms, "response": resp}
        out.append(item)
        print(f"[{i}/{len(selected)}] {item['id']} status={status} pred={pred or '-'} gold={gold or '-'} accurate={accurate} {ms}ms", flush=True)
    return out

def report(results, outdir, endpoint):
    outdir.mkdir(parents=True, exist_ok=True)
    total = len(results); refused = sum(x["refused"] for x in results); answered = total - refused; correct = sum(x["accurate"] for x in results)
    wrong = [x for x in results if not x["refused"] and not x["accurate"]]; refusals = [x for x in results if x["refused"]]
    by_type = {}
    for x in results:
        b = by_type.setdefault(x["qa_type"] or "unclassified", {"total": 0, "answered": 0, "refused": 0, "correct": 0, "wrong": 0})
        b["total"] += 1; b["answered"] += int(not x["refused"]); b["refused"] += int(x["refused"]); b["correct"] += int(x["accurate"]); b["wrong"] += int(not x["refused"] and not x["accurate"])
    summary = {"total": total, "answered": answered, "refused": refused, "correct": correct, "wrong_answered": len(wrong), "accuracy_over_all": correct / total if total else 0, "accuracy_over_answered": correct / answered if answered else 0, "refused_ids": [x["id"] for x in refusals], "wrong_ids": [x["id"] for x in wrong], "by_qa_type": by_type}
    (outdir / "qa_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (outdir / "qa_results.jsonl").open("w", encoding="utf-8") as f:
        for x in results: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    cols = ["id", "qa_type", "gold_answer", "predicted_answer", "status", "refused", "accurate", "refusal_reason", "source_title", "system_answer", "elapsed_ms"]
    with (outdir / "qa_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(results)
    md = ["# QA HTTP Evaluation Summary", "", f"- Endpoint: `POST {endpoint}` (same as frontend)", "- Sent only question and options; gold answer/evidence were not sent.", "- DeepSeek remained enabled according to `.env`; local mode was not used.", f"- Total: {total}", f"- Answered: {answered}", f"- Refused/request failed: {refused}", f"- Correct: {correct}", f"- Wrong among answered: {len(wrong)}", f"- Overall accuracy: {correct / total:.2%}" if total else "- Overall accuracy: 0.00%", f"- Answered accuracy: {correct / answered:.2%}" if answered else "- Answered accuracy: 0.00%", "", "## By type", "", "|Type|Total|Answered|Refused|Correct|Wrong|", "|---|---:|---:|---:|---:|---:|"]
    for typ, b in by_type.items():
        md.append(f"|{typ}|{b['total']}|{b['answered']}|{b['refused']}|{b['correct']}|{b['wrong']}|")
    md += ["", "## Refused/request failed", "", "|ID|Status|Reason|", "|---|---|---|"]
    md += [f"|{x['id']}|{x['status']}|{x['refusal_reason'] or 'unspecified'}|" for x in refusals] or ["|none| | |"]
    md += ["", "## Wrong answered", "", "|ID|Gold|Predicted|Status|", "|---|---|---|---|"]
    md += [f"|{x['id']}|{''.join(x['gold_answer'])}|{''.join(x['predicted_answer']) or 'unparsed'}|{x['status']}|" for x in wrong] or ["|none| | | |"]
    (outdir / "QA_HTTP_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--qa", type=Path, default=Path(r"D:\金融科技\QA数据.xlsx")); ap.add_argument("--endpoint", default="http://127.0.0.1:8000/api/v1/ask"); ap.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "qa_eval_http_full"); ap.add_argument("--limit", type=int, default=None); ap.add_argument("--timeout", type=float, default=180)
    args = ap.parse_args(); report(evaluate(load_rows(args.qa), args.endpoint, args.limit, args.timeout), args.output_dir, args.endpoint)

if __name__ == "__main__":
    main()
