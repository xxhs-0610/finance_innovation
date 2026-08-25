from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.indexing.build_kb import build_kb


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the module-2 knowledge base.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a module-2 JSON config (default: configs/default.json).",
    )
    parser.add_argument("--parsed-docs", default=None, help="Override the configured document JSONL path.")
    parser.add_argument("--parsed-tables", default=None, help="Override the configured table evidence JSONL path.")
    parser.add_argument("--processed-dir", default=None, help="Override the configured processed output directory.")
    parser.add_argument("--indexes-dir", default=None, help="Override the configured index output directory.")
    return parser.parse_args()


def load_paths(config_path: Path) -> dict[str, str]:
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"Module-2 config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    paths = config.get("paths")
    if not isinstance(paths, dict):
        raise ValueError(f"Config must contain a paths object: {config_path}")
    return paths


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    args = parse_args()
    config_path = args.config or DEFAULT_CONFIG_PATH
    paths = load_paths(config_path)

    parsed_docs = project_path(args.parsed_docs or paths["parsed_docs"])
    parsed_tables = project_path(args.parsed_tables or paths["parsed_tables"])
    processed_dir = project_path(args.processed_dir or paths["processed_dir"])
    indexes_dir = project_path(args.indexes_dir or paths["indexes_dir"])

    stats = build_kb(
        parsed_docs,
        parsed_tables,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
    )
    print(f"Config: {config_path}")
    print(f"Documents: {parsed_docs}")
    print(f"Tables: {parsed_tables}")
    print("Knowledge base built successfully:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
