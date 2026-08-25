from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "parsing.json"
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "raw" / "nfra_page_attachments_500"
DEFAULT_EXTERNAL_SOURCE_DIR = (
    WORKSPACE_ROOT
    / "docx"
    / "03-金融大模型与智能体赛道-南京银行-面向银行业监管制度与统计报表的可信RAG问答"
    / "数据集"
    / "nfra_page_attachments_500"
)


def load_parsing_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    username: str = "root"
    password: str = ""
    database: str = "finance_innovation_rag"

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        config = load_parsing_config().get("database", {})
        database = os.getenv("RAG_DB_NAME", config.get("database", "finance_innovation_rag"))
        if not re.fullmatch(r"[A-Za-z0-9_]+", database):
            raise ValueError("RAG_DB_NAME may contain only letters, numbers, and underscores")
        return cls(
            host=os.getenv("RAG_DB_HOST", config.get("host", "127.0.0.1")),
            port=int(os.getenv("RAG_DB_PORT", str(config.get("port", 3306)))),
            username=os.getenv("RAG_DB_USER", config.get("username", "root")),
            password=os.getenv("RAG_DB_PASSWORD", ""),
            database=database,
        )


def input_dir_from_env() -> Path:
    config = load_parsing_config().get("paths", {})
    configured = config.get("input_dir", str(DEFAULT_INPUT_DIR.relative_to(PROJECT_ROOT)))
    path = Path(os.getenv("RAG_INPUT_DIR", configured)).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def external_source_dir_from_env() -> Path:
    return Path(os.getenv("RAG_SOURCE_INPUT_DIR", str(DEFAULT_EXTERNAL_SOURCE_DIR))).expanduser().resolve()


def output_paths() -> dict[str, Path]:
    config = load_parsing_config().get("paths", {})

    def resolve(key: str, default: str) -> Path:
        value = Path(config.get(key, default))
        return (PROJECT_ROOT / value).resolve() if not value.is_absolute() else value.resolve()

    return {
        "parsed_docs": resolve("parsed_docs", "data/parsed/docs/parsed_docs.jsonl"),
        "parsed_tables": resolve("parsed_tables", "data/parsed/tables/parsed_tables.jsonl"),
        "table_evidence": resolve("table_evidence", "data/parsed/tables/table_evidence.jsonl"),
        "doc_meta": resolve("doc_meta", "data/parsed/meta/doc_meta.jsonl"),
        "manifest": resolve("manifest", "data/parsed/meta/generated_manifest.jsonl"),
        "report": resolve("report", "reports/module1_parsing_report.md"),
    }


def display_local_path(path: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), PROJECT_ROOT)).as_posix()
    except ValueError:
        return str(path.resolve())
