from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.indexing.build_kb import build_kb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the module-2 knowledge base.")
    parser.add_argument("--parsed-docs", default="data/parsed/parsed_docs.jsonl")
    parser.add_argument("--parsed-tables", default="data/parsed/parsed_tables.jsonl")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--indexes-dir", default="indexes")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Copy data/samples into data/parsed before building.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sample:
        Path("data/parsed").mkdir(parents=True, exist_ok=True)
        for name in ("parsed_docs.jsonl", "parsed_tables.jsonl", "doc_meta.jsonl"):
            shutil.copyfile(Path("data/samples") / name, Path("data/parsed") / name)

    stats = build_kb(
        args.parsed_docs,
        args.parsed_tables,
        processed_dir=args.processed_dir,
        indexes_dir=args.indexes_dir,
    )
    print("Knowledge base built successfully:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
