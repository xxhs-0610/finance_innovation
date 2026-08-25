"""Vector Index Repository Layer."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class VectorIndexRepository:
    """DAO for checking vector index health and status."""

    def __init__(self, index_dir: Optional[Path | str] = None):
        self.index_dir = Path(index_dir) if index_dir else Path("indexes/kb_rebuild")

    def get_info(self) -> dict[str, Any]:
        has_faiss = (self.index_dir / "faiss.index").exists()
        has_embeddings = (self.index_dir / "embeddings.npy").exists()
        has_meta = (self.index_dir / "vector_meta.json").exists()

        return {
            "index_path": str(self.index_dir),
            "is_ready": has_faiss or has_embeddings,
            "has_faiss": has_faiss,
            "has_embeddings": has_embeddings,
            "has_meta": has_meta,
            "embedding_dimension": 768,
        }


vector_repo = VectorIndexRepository()
