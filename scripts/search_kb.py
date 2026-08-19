from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.indexing.index_reader import KnowledgeBaseReader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the local knowledge base.")
    parser.add_argument("query")
    parser.add_argument("--db-path", default="data/processed/kb_rebuild/metadata.db")
    parser.add_argument("--index-dir", default=None, help="Directory containing faiss.index for vector/hybrid modes.")
    parser.add_argument("--mode", choices=["bm25", "vector", "hybrid"], default="bm25")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, help="Number of BM25 candidates before reranking.")
    parser.add_argument("--no-rerank", action="store_true", help="Disable the lightweight reranking layer.")
    parser.add_argument("--chunk-type", choices=["clause", "table"])
    parser.add_argument("--title")
    parser.add_argument("--issuer")
    parser.add_argument("--publish-date")
    parser.add_argument("--embedding-backend", choices=["sentence-transformers", "hashing"], default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--bm25-weight", type=float, default=0.5)
    parser.add_argument("--vector-weight", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    filters = {
        key: value
        for key, value in {
            "title": args.title,
            "issuer": args.issuer,
            "publish_date": args.publish_date,
        }.items()
        if value
    }
    reader = KnowledgeBaseReader(
        args.db_path,
        vector_index_dir=args.index_dir,
        embedding_backend=args.embedding_backend,
        model_name=args.model_name,
        device=args.device,
    )
    if args.mode == "bm25":
        results = reader.search(
            args.query,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            chunk_type=args.chunk_type,
            filters=filters,
            rerank=not args.no_rerank,
        )
    elif args.mode == "vector":
        results = reader.vector_search(
            args.query,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            chunk_type=args.chunk_type,
            filters=filters,
            rerank=not args.no_rerank,
        )
    else:
        results = reader.hybrid_search(
            args.query,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            chunk_type=args.chunk_type,
            filters=filters,
            rerank=not args.no_rerank,
            bm25_weight=args.bm25_weight,
            vector_weight=args.vector_weight,
        )
    print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
