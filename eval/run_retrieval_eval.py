from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.indexing.index_reader import KnowledgeBaseReader
from app.shared.jsonl import read_jsonl, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate module-2 retrieval quality.")
    parser.add_argument("--db-path", default="data/processed/metadata.db")
    parser.add_argument("--eval-set", default="eval/retrieval_eval_set.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int)
    parser.add_argument("--no-rerank", action="store_true", help="Evaluate raw BM25/FTS ranking.")
    parser.add_argument("--output", help="Optional JSONL path for per-question results.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    cases = list(read_jsonl(args.eval_set))
    if not cases:
        raise SystemExit(f"No evaluation cases found: {args.eval_set}")

    reader = KnowledgeBaseReader(args.db_path)
    rows: list[dict[str, Any]] = []

    for case in cases:
        question = case["question"]
        results = reader.search(
            question,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            rerank=not args.no_rerank,
        )
        rank = first_relevant_rank(case.get("expected", {}), results)
        top1 = results[0] if results else None
        rows.append(
            {
                "id": case.get("id", ""),
                "category": case.get("category", ""),
                "question": question,
                "rank": rank,
                "hit@1": rank == 1,
                f"hit@{args.top_k}": rank is not None and rank <= args.top_k,
                "mrr": 0.0 if rank is None else 1.0 / rank,
                "expected": case.get("expected", {}),
                "top1": compact_result(top1) if top1 else None,
                "results": [compact_result(item) for item in results],
            }
        )

    print_summary(rows, top_k=args.top_k, rerank=not args.no_rerank)
    if args.output:
        write_jsonl(args.output, rows)
        print(f"\nDetailed report written to: {args.output}")


def first_relevant_rank(expected: dict[str, Any], results: list) -> int | None:
    for index, result in enumerate(results, start=1):
        if is_relevant(expected, result):
            return index
    return None


def is_relevant(expected: dict[str, Any], result: Any) -> bool:
    chunk_ids = set(expected.get("chunk_ids") or [])
    if chunk_ids and result.chunk_id in chunk_ids:
        return True

    doc_ids = set(expected.get("doc_ids") or [])
    chunk_type = expected.get("chunk_type")
    if doc_ids and result.source.doc_id not in doc_ids:
        return False
    if chunk_type and result.chunk_type != chunk_type:
        return False

    haystack = result_haystack(result)
    must_all = expected.get("must_contain_all") or []
    must_any = expected.get("must_contain_any") or []
    if must_all and not all(item in haystack for item in must_all):
        return False
    if must_any and not any(item in haystack for item in must_any):
        return False

    return bool(doc_ids or chunk_type or must_all or must_any)


def result_haystack(result: Any) -> str:
    source = result.source
    parts = [
        result.chunk_id,
        result.chunk_type,
        result.text,
        source.doc_id,
        source.title,
        source.issuer,
        source.publish_date,
        " ".join(source.section_path),
        source.clause_no,
        source.sheet_name,
        source.table_name,
        source.cell_ref,
        json.dumps(result.metadata or {}, ensure_ascii=False),
    ]
    return " ".join(str(part) for part in parts if part)


def compact_result(result: Any) -> dict[str, Any]:
    return {
        "chunk_id": result.chunk_id,
        "chunk_type": result.chunk_type,
        "score": round(result.score, 4),
        "doc_id": result.source.doc_id,
        "title": result.source.title,
        "text": result.text[:180],
    }


def print_summary(rows: list[dict[str, Any]], *, top_k: int, rerank: bool) -> None:
    total = len(rows)
    hit1 = sum(1 for row in rows if row["hit@1"])
    hitk_key = f"hit@{top_k}"
    hitk = sum(1 for row in rows if row[hitk_key])
    mrr = sum(row["mrr"] for row in rows) / total

    mode = "BM25/FTS + lightweight rerank" if rerank else "BM25/FTS without rerank"
    print(f"Retrieval evaluation mode: {mode}")
    print(f"Cases: {total}")
    print(f"Hit@1: {hit1}/{total} = {hit1 / total:.2%}")
    print(f"Hit@{top_k}: {hitk}/{total} = {hitk / total:.2%}")
    print(f"MRR: {mrr:.4f}")

    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(row.get("category") or "未分类", []).append(row)

    print("\nBy category:")
    for category, items in by_category.items():
        c_hitk = sum(1 for row in items if row[hitk_key])
        c_mrr = sum(row["mrr"] for row in items) / len(items)
        print(f"- {category}: Hit@{top_k} {c_hitk}/{len(items)}, MRR {c_mrr:.4f}")

    misses = [row for row in rows if not row[hitk_key]]
    if misses:
        print("\nMissed cases:")
        for row in misses:
            top1 = row["top1"] or {}
            print(f"- {row['id']} | {row['question']} | top1={top1.get('chunk_id')} {top1.get('title')}")


if __name__ == "__main__":
    main()
