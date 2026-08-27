from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path_str in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from app.retrieval.hybrid_retriever import retrieve
from app.schemas.chunk_schema import SearchResult
from app.shared.jsonl import read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the module-3 pipeline.")
    parser.add_argument("--eval-set", default="eval/retrieval_eval_set.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--db-path", default="data/processed/kb_rebuild/metadata.db")
    parser.add_argument("--index-dir", default="indexes/kb_rebuild")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k < 1:
        raise SystemExit("--top-k must be greater than zero")
    rows: list[dict[str, Any]] = []
    for case in read_jsonl(args.eval_set):
        response = retrieve(
            case["question"],
            top_k=args.top_k,
            db_path=args.db_path,
            index_dir=args.index_dir,
        )
        rank = first_relevant_rank(case.get("expected", {}), response.evidence)
        rows.append(
            {
                "id": case.get("id", ""),
                "question": case["question"],
                "status": response.status,
                "rank": rank,
                "top1": response.evidence[0].chunk_id if response.evidence else "",
            }
        )

    total = len(rows)
    hit1 = sum(row["rank"] == 1 for row in rows)
    hitk = sum(
        row["rank"] is not None and row["rank"] <= args.top_k for row in rows
    )
    mrr = sum(0.0 if row["rank"] is None else 1.0 / row["rank"] for row in rows)
    mrr = mrr / total if total else 0.0
    print(f"Cases: {total}")
    print(f"Hit@1: {hit1}/{total} = {hit1 / total:.2%}" if total else "Hit@1: n/a")
    print(
        f"Hit@{args.top_k}: {hitk}/{total} = {hitk / total:.2%}"
        if total
        else f"Hit@{args.top_k}: n/a"
    )
    print(f"MRR: {mrr:.4f}")
    for row in rows:
        print(
            f"{row['id']} | status={row['status']} | "
            f"rank={row['rank']} | top1={row['top1']}"
        )


def first_relevant_rank(
    expected: dict[str, Any], results: list[SearchResult]
) -> int | None:
    for rank, result in enumerate(results, start=1):
        if is_relevant(expected, result):
            return rank
    return None


def is_relevant(expected: dict[str, Any], result: SearchResult) -> bool:
    chunk_ids = set(expected.get("chunk_ids") or [])
    if chunk_ids and result.chunk_id in chunk_ids:
        return True
    doc_ids = set(expected.get("doc_ids") or [])
    if doc_ids and result.source.doc_id not in doc_ids:
        return False
    chunk_type = expected.get("chunk_type")
    if chunk_type and result.chunk_type != chunk_type:
        return False
    haystack = " ".join(
        [
            result.chunk_id,
            result.text,
            result.source.doc_id,
            result.source.title,
            " ".join(result.source.section_path),
            json.dumps(result.metadata, ensure_ascii=False),
        ]
    )
    must_all = expected.get("must_contain_all") or []
    must_any = expected.get("must_contain_any") or []
    if must_all and not all(item in haystack for item in must_all):
        return False
    if must_any and not any(item in haystack for item in must_any):
        return False
    return bool(doc_ids or chunk_type or must_all or must_any)


if __name__ == "__main__":
    main()
