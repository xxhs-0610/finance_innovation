from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path_str in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from app.indexing.vector_index import DEFAULT_MODEL_NAME, build_vector_index


DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "backend" / "configs" / "default.json"
    if (PROJECT_ROOT / "backend" / "configs" / "default.json").exists()
    else PROJECT_ROOT / "configs" / "default.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS vector index for module-2 chunks.")
    parser.add_argument("--config", type=Path, default=None, help="Path to config JSON.")
    parser.add_argument("--processed-dir", default=None, help="Directory containing clause/table chunks.")
    parser.add_argument("--indexes-dir", default=None, help="Directory to save vector index files.")
    parser.add_argument("--clause-chunks", default=None, help="Override clause_chunks.jsonl path.")
    parser.add_argument("--table-chunks", default=None, help="Override table_chunks.jsonl path.")
    parser.add_argument(
        "--embedding-backend",
        choices=["sentence-transformers", "hashing"],
        default="sentence-transformers",
        help="Use sentence-transformers for real embeddings, or hashing for offline smoke tests.",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="SentenceTransformer model name.")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default=None, help="Optional device, for example cpu or cuda.")
    parser.add_argument("--limit", type=int, default=None, help="Only index first N chunks, useful for smoke tests.")
    parser.add_argument("--no-normalize", action="store_true", help="Disable L2 normalization.")
    parser.add_argument("--no-save-embeddings", action="store_true", help="Skip writing embeddings.npy.")
    parser.add_argument("--query-prefix", default="", help="Optional query prefix for embedding models.")
    parser.add_argument("--passage-prefix", default="", help="Optional passage prefix for embedding models.")
    return parser.parse_args()


def load_paths(config_path: Path) -> dict[str, str]:
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    paths = config.get("paths")
    if not isinstance(paths, dict):
        raise ValueError(f"Config must contain a paths object: {config_path}")
    return paths


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    args = parse_args()
    paths = load_paths(args.config or DEFAULT_CONFIG_PATH)
    processed_dir = project_path(args.processed_dir or paths["processed_dir"])
    indexes_dir = project_path(args.indexes_dir or paths["indexes_dir"])
    clause_chunks = project_path(args.clause_chunks) if args.clause_chunks else processed_dir / "clause_chunks.jsonl"
    table_chunks = project_path(args.table_chunks) if args.table_chunks else processed_dir / "table_chunks.jsonl"

    model_name = args.model_name
    if args.embedding_backend == "hashing" and model_name == DEFAULT_MODEL_NAME:
        model_name = None

    stats = build_vector_index(
        clause_chunks_path=clause_chunks,
        table_chunks_path=table_chunks,
        output_dir=indexes_dir,
        embedding_backend=args.embedding_backend,
        model_name=model_name,
        batch_size=args.batch_size,
        device=args.device,
        normalize_embeddings=not args.no_normalize,
        save_embeddings=not args.no_save_embeddings,
        limit=args.limit,
        query_prefix=args.query_prefix,
        passage_prefix=args.passage_prefix,
    )
    print("Vector index built successfully:")
    for key, value in stats.to_dict().items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
