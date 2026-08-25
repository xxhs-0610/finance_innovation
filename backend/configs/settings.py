"""Centralized Application Configuration and Environment Settings."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


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
    index_dir: Path = Field(default_factory=lambda: Path("indexes/kb_rebuild"))
    frontend_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1] / "frontend")


class ModelSettings(BaseModel):
    embedding_model_name_or_path: str = "Model/bge-small-zh-v1.5"
    embedding_dimension: int = 768
    deepseek_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"


class AppConfig(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)


settings = AppConfig()
