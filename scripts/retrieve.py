from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.retrieval.hybrid_retriever import retrieve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the module-3 retrieval pipeline.")
    parser.add_argument("question")
    parser.add_argument("--db-path", default="data/processed/kb_rebuild/metadata.db")
    parser.add_argument("--index-dir", default="indexes/kb_rebuild")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k < 1:
        raise SystemExit("--top-k must be greater than zero")
    response = retrieve(
        args.question,
        top_k=args.top_k,
        db_path=args.db_path,
        index_dir=args.index_dir,
    )
    print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
