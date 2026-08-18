from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.indexing.text_utils import clean_text, query_tokens
from app.shared.jsonl import read_jsonl


EmbeddingBackend = Literal["sentence-transformers", "hashing"]

DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBEDDING_BACKEND: EmbeddingBackend = "sentence-transformers"
DEFAULT_HASHING_DIM = 384
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_MODEL_DIR = PROJECT_ROOT / "Model" / "bge-small-zh-v1.5"


@dataclass
class VectorHit:
    offset: int
    chunk_id: str
    chunk_type: str
    doc_id: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VectorBuildStats:
    chunk_count: int
    dimension: int
    embedding_backend: str
    model_name: str
    index_path: str
    embeddings_path: str
    chunk_id_map_path: str
    vector_meta_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SentenceTransformerEncoder:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        *,
        device: str | None = None,
        query_prefix: str = "",
        passage_prefix: str = "",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. Install it before building the vector index."
            ) from exc

        resolved_model_name = _resolve_embedding_model_name(model_name)
        self.model_name = resolved_model_name
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.model = SentenceTransformer(resolved_model_name, device=device)

    def encode_passages(
        self,
        texts: list[str],
        *,
        batch_size: int = 64,
        normalize_embeddings: bool = True,
    ):
        return self._encode(
            [self.passage_prefix + text for text in texts],
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
        )

    def encode_queries(
        self,
        texts: list[str],
        *,
        batch_size: int = 64,
        normalize_embeddings: bool = True,
    ):
        return self._encode(
            [self.query_prefix + text for text in texts],
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
        )

    def _encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
    ):
        np = _import_numpy()
        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype="float32")


class HashingTextEncoder:
    """Small deterministic dense encoder used for smoke tests and offline fallback.

    It is not a replacement for a real semantic embedding model, but it lets tests
    build a FAISS index without downloading model weights.
    """

    def __init__(self, *, dimension: int = DEFAULT_HASHING_DIM) -> None:
        self.model_name = f"hashing-{dimension}"
        self.dimension = dimension

    def encode_passages(
        self,
        texts: list[str],
        *,
        batch_size: int = 64,
        normalize_embeddings: bool = True,
    ):
        return self._encode(texts, normalize_embeddings=normalize_embeddings)

    def encode_queries(
        self,
        texts: list[str],
        *,
        batch_size: int = 64,
        normalize_embeddings: bool = True,
    ):
        return self._encode(texts, normalize_embeddings=normalize_embeddings)

    def _encode(self, texts: list[str], *, normalize_embeddings: bool):
        np = _import_numpy()
        vectors = np.zeros((len(texts), self.dimension), dtype="float32")
        for row_no, text in enumerate(texts):
            tokens = query_tokens(text, max_tokens=256)
            if not tokens:
                tokens = [clean_text(text)]
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                value = int.from_bytes(digest, byteorder="little", signed=False)
                col_no = value % self.dimension
                sign = 1.0 if (value >> 8) & 1 else -1.0
                weight = 1.0 + min(len(token), 12) / 12
                vectors[row_no, col_no] += sign * weight
        if normalize_embeddings:
            _l2_normalize(vectors)
        return vectors


def create_text_encoder(
    *,
    embedding_backend: EmbeddingBackend = DEFAULT_EMBEDDING_BACKEND,
    model_name: str | None = None,
    device: str | None = None,
    query_prefix: str = "",
    passage_prefix: str = "",
) -> SentenceTransformerEncoder | HashingTextEncoder:
    if embedding_backend == "hashing":
        dimension = DEFAULT_HASHING_DIM
        if model_name and model_name.startswith("hashing-"):
            try:
                dimension = int(model_name.rsplit("-", 1)[1])
            except ValueError:
                dimension = DEFAULT_HASHING_DIM
        return HashingTextEncoder(dimension=dimension)
    if embedding_backend == "sentence-transformers":
        return SentenceTransformerEncoder(
            model_name or DEFAULT_MODEL_NAME,
            device=device,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )
    raise ValueError(f"Unsupported embedding backend: {embedding_backend}")


def build_vector_index(
    *,
    clause_chunks_path: str | Path,
    table_chunks_path: str | Path,
    output_dir: str | Path,
    embedding_backend: EmbeddingBackend = DEFAULT_EMBEDDING_BACKEND,
    model_name: str | None = None,
    batch_size: int = 64,
    device: str | None = None,
    normalize_embeddings: bool = True,
    save_embeddings: bool = True,
    limit: int | None = None,
    query_prefix: str = "",
    passage_prefix: str = "",
) -> VectorBuildStats:
    np = _import_numpy()
    faiss = _import_faiss()

    clause_chunks_path = Path(clause_chunks_path)
    table_chunks_path = Path(table_chunks_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not clause_chunks_path.exists():
        raise FileNotFoundError(f"Clause chunks file not found: {clause_chunks_path}")
    if not table_chunks_path.exists():
        raise FileNotFoundError(f"Table chunks file not found: {table_chunks_path}")

    encoder = create_text_encoder(
        embedding_backend=embedding_backend,
        model_name=model_name,
        device=device,
        query_prefix=query_prefix,
        passage_prefix=passage_prefix,
    )
    resolved_model_name = getattr(encoder, "model_name", model_name or DEFAULT_MODEL_NAME)

    embeddings_parts = []
    chunk_map: list[dict[str, Any]] = []
    batch_texts: list[str] = []
    batch_records: list[dict[str, str]] = []

    def flush_batch() -> None:
        if not batch_texts:
            return
        vectors = encoder.encode_passages(
            batch_texts,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
        )
        embeddings_parts.append(np.asarray(vectors, dtype="float32"))
        start_offset = len(chunk_map)
        for offset, record in enumerate(batch_records, start=start_offset):
            chunk_map.append(
                {
                    "offset": offset,
                    "chunk_id": record["chunk_id"],
                    "chunk_type": record["chunk_type"],
                    "doc_id": record["doc_id"],
                }
            )
        batch_texts.clear()
        batch_records.clear()
        print(f"Embedded chunks: {len(chunk_map)}", flush=True)

    for record in iter_vector_source_chunks(clause_chunks_path, table_chunks_path):
        batch_texts.append(record["text"])
        batch_records.append(record)
        if len(batch_texts) >= batch_size:
            flush_batch()
        if limit is not None and len(chunk_map) + len(batch_records) >= limit:
            break
    flush_batch()

    if not embeddings_parts:
        raise ValueError("No chunks found for vector indexing.")

    embeddings = np.vstack(embeddings_parts).astype("float32", copy=False)
    if normalize_embeddings:
        _l2_normalize(embeddings)

    dimension = int(embeddings.shape[1])
    index = faiss.IndexFlatIP(dimension) if normalize_embeddings else faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    index_path = output_dir / "faiss.index"
    embeddings_path = output_dir / "embeddings.npy"
    chunk_id_map_path = output_dir / "chunk_id_map.json"
    vector_meta_path = output_dir / "vector_meta.json"

    _write_faiss_index(faiss, index, index_path)
    if save_embeddings:
        np.save(embeddings_path, embeddings)
    else:
        embeddings_path.write_text(
            "embeddings.npy was skipped because save_embeddings=False.\n",
            encoding="utf-8",
        )

    chunk_id_map_path.write_text(
        json.dumps({"version": 1, "items": chunk_map}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    vector_meta = {
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "embedding_backend": embedding_backend,
        "model_name": resolved_model_name,
        "dimension": dimension,
        "chunk_count": len(chunk_map),
        "normalize_embeddings": normalize_embeddings,
        "metric": "inner_product_cosine" if normalize_embeddings else "l2_distance",
        "source_files": {
            "clause_chunks": str(clause_chunks_path),
            "table_chunks": str(table_chunks_path),
        },
        "output_files": {
            "faiss_index": str(index_path),
            "embeddings": str(embeddings_path),
            "chunk_id_map": str(chunk_id_map_path),
            "vector_meta": str(vector_meta_path),
        },
    }
    vector_meta_path.write_text(
        json.dumps(vector_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return VectorBuildStats(
        chunk_count=len(chunk_map),
        dimension=dimension,
        embedding_backend=embedding_backend,
        model_name=resolved_model_name,
        index_path=str(index_path),
        embeddings_path=str(embeddings_path),
        chunk_id_map_path=str(chunk_id_map_path),
        vector_meta_path=str(vector_meta_path),
    )


class VectorIndexSearcher:
    def __init__(
        self,
        index_dir: str | Path,
        *,
        embedding_backend: EmbeddingBackend | None = None,
        model_name: str | None = None,
        device: str | None = None,
        query_prefix: str = "",
        passage_prefix: str = "",
    ) -> None:
        self.index_dir = Path(index_dir)
        self.index_path = self.index_dir / "faiss.index"
        self.chunk_id_map_path = self.index_dir / "chunk_id_map.json"
        self.vector_meta_path = self.index_dir / "vector_meta.json"

        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.index_path}")
        if not self.chunk_id_map_path.exists():
            raise FileNotFoundError(f"Chunk id map not found: {self.chunk_id_map_path}")

        self.meta = _read_json(self.vector_meta_path) if self.vector_meta_path.exists() else {}
        backend = embedding_backend or self.meta.get("embedding_backend") or DEFAULT_EMBEDDING_BACKEND
        resolved_model_name = model_name or self.meta.get("model_name") or DEFAULT_MODEL_NAME
        self.normalize_embeddings = bool(self.meta.get("normalize_embeddings", True))

        faiss = _import_faiss()
        self.index = _read_faiss_index(faiss, self.index_path)
        self.chunk_map = _load_chunk_id_map(self.chunk_id_map_path)
        self.encoder = create_text_encoder(
            embedding_backend=backend,
            model_name=resolved_model_name,
            device=device,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int | None = None,
        chunk_type: str | None = None,
        batch_size: int = 1,
    ) -> list[VectorHit]:
        np = _import_numpy()
        query = clean_text(query)
        if not query:
            return []

        search_k = min(len(self.chunk_map), max(top_k, candidate_k or top_k))
        if search_k <= 0:
            return []

        query_vector = self.encoder.encode_queries(
            [query],
            batch_size=batch_size,
            normalize_embeddings=self.normalize_embeddings,
        )
        query_vector = np.asarray(query_vector, dtype="float32")
        if self.normalize_embeddings:
            _l2_normalize(query_vector)

        scores, offsets = self.index.search(query_vector, search_k)
        hits: list[VectorHit] = []
        for score, offset in zip(scores[0], offsets[0]):
            if offset < 0 or offset >= len(self.chunk_map):
                continue
            item = self.chunk_map[int(offset)]
            if chunk_type and item.get("chunk_type") != chunk_type:
                continue
            hits.append(
                VectorHit(
                    offset=int(offset),
                    chunk_id=str(item["chunk_id"]),
                    chunk_type=str(item.get("chunk_type") or ""),
                    doc_id=str(item.get("doc_id") or ""),
                    score=float(score),
                )
            )
            if len(hits) >= top_k:
                break
        return hits


def iter_vector_source_chunks(
    clause_chunks_path: str | Path,
    table_chunks_path: str | Path,
):
    for path in (Path(clause_chunks_path), Path(table_chunks_path)):
        for row in read_jsonl(path):
            chunk_id = clean_text(row.get("chunk_id"))
            text = clean_text(row.get("retrieval_text") or row.get("text"))
            if not chunk_id or not text:
                continue
            yield {
                "chunk_id": chunk_id,
                "chunk_type": clean_text(row.get("chunk_type")),
                "doc_id": clean_text(row.get("doc_id")),
                "text": text,
            }


def _load_chunk_id_map(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        result = []
        for offset, item in enumerate(data):
            if isinstance(item, str):
                result.append({"offset": offset, "chunk_id": item, "chunk_type": "", "doc_id": ""})
            elif isinstance(item, dict):
                result.append({"offset": offset, **item})
        return result
    raise ValueError(f"Invalid chunk id map format: {path}")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_embedding_model_name(model_name: str | None) -> str:
    if model_name:
        candidate = Path(model_name)
        if candidate.exists():
            return str(candidate)
        if model_name == DEFAULT_MODEL_NAME and DEFAULT_LOCAL_MODEL_DIR.exists():
            return str(DEFAULT_LOCAL_MODEL_DIR)
        return model_name
    if DEFAULT_LOCAL_MODEL_DIR.exists():
        return str(DEFAULT_LOCAL_MODEL_DIR)
    return DEFAULT_MODEL_NAME


def _import_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError("numpy is required for vector indexing.") from exc
    return np


def _import_faiss():
    try:
        import faiss
    except ImportError as exc:
        raise ImportError(
            "faiss is required for vector indexing. On Windows, install it with: "
            "conda install -c pytorch -c conda-forge faiss-cpu -y"
        ) from exc
    return faiss


def _write_faiss_index(faiss, index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        faiss.write_index(index, str(path))
        return
    except RuntimeError:
        pass

    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="faiss_", suffix=".index", delete=False) as temp_file:
            temp_name = temp_file.name
        faiss.write_index(index, temp_name)
        shutil.move(temp_name, path)
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()


def _read_faiss_index(faiss, path: Path):
    try:
        return faiss.read_index(str(path))
    except RuntimeError:
        pass

    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="faiss_", suffix=".index", delete=False) as temp_file:
            temp_name = temp_file.name
        shutil.copyfile(path, temp_name)
        return faiss.read_index(temp_name)
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()


def _l2_normalize(vectors) -> None:
    np = _import_numpy()
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors /= norms
