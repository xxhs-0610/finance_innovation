"""Centralized Application Configuration and Environment Settings."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# Automatically load environment variables from .env
try:
    from dotenv import load_dotenv
    root_dir = Path(__file__).resolve().parents[2]
    for env_path in [root_dir / ".env", Path(__file__).resolve().parents[1] / ".env", Path.cwd() / ".env"]:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
            break
except Exception:
    pass


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["*"]
    debug: bool = False


class PathSettings(BaseModel):
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1])
    raw_data_dir: Path = Field(default_factory=lambda: Path("data/raw/nfra_page_attachments_500"))
    parsed_docs_dir: Path = Field(default_factory=lambda: Path("data/parsed/docs"))
    parsed_tables_dir: Path = Field(default_factory=lambda: Path("data/parsed/tables"))
    parsed_meta_dir: Path = Field(default_factory=lambda: Path("data/parsed/meta"))
    sqlite_db_path: Path = Field(default_factory=lambda: Path("data/processed/kb_rebuild/metadata.db"))
    index_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2] / "indexes" / "kb_rebuild")
    frontend_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2] / "frontend")


class ModelSettings(BaseModel):
    embedding_model_name_or_path: str = "Model/bge-small-zh-v1.5"
    embedding_dimension: int = 512
    deepseek_enabled: bool = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_ENABLED", "false").lower() in ("true", "1", "yes", "on")
    )
    deepseek_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    deepseek_model: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    )
    deepseek_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "45"))
    )
    deepseek_max_retries: int = Field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))
    )


class LogSettings(BaseModel):
    level: str = "INFO"
    log_file: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2] / "logs" / "app.log")
    enable_console: bool = True
    enable_file: bool = True
    max_bytes: int = 20 * 1024 * 1024  # 20MB
    backup_count: int = 5


class AppConfig(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    logging: LogSettings = Field(default_factory=LogSettings)


settings = AppConfig()
