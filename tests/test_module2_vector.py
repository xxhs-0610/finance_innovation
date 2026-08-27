from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.indexing.build_kb import build_kb
from app.indexing.index_reader import KnowledgeBaseReader
from app.indexing.vector_index import build_vector_index
from app.repositories.vector_repo import VectorIndexRepository


def _has_vector_deps() -> bool:
    return importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("faiss") is not None


@unittest.skipUnless(_has_vector_deps(), "numpy/faiss are required for vector index tests")
class Module2VectorTest(unittest.TestCase):
    def test_build_vector_index_and_hybrid_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            indexes_dir = root / "indexes"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=indexes_dir,
            )

            stats = build_vector_index(
                clause_chunks_path=processed_dir / "clause_chunks.jsonl",
                table_chunks_path=processed_dir / "table_chunks.jsonl",
                output_dir=indexes_dir,
                embedding_backend="hashing",
                batch_size=2,
            )

            self.assertEqual(stats.chunk_count, 6)
            self.assertTrue((indexes_dir / "embeddings.npy").exists())
            self.assertTrue((indexes_dir / "faiss.index").exists())
            self.assertTrue((indexes_dir / "chunk_id_map.json").exists())
            self.assertTrue((indexes_dir / "vector_meta.json").exists())

            # Test VectorIndexRepository with temp directory
            repo = VectorIndexRepository(index_dir=indexes_dir)
            info = repo.get_info()
            self.assertTrue(info["is_ready"])
            self.assertTrue(info["has_faiss"])
            self.assertTrue(info["has_chunk_id_map"])

            detailed = repo.get_detailed_status()
            self.assertEqual(detailed["status"], "healthy")
            self.assertEqual(len(detailed["files"]), 5)

            reader = KnowledgeBaseReader(
                processed_dir / "metadata.db",
                vector_index_dir=indexes_dir,
                embedding_backend="hashing",
            )
            vector_results = reader.vector_search("资本充足率", top_k=3)
            hybrid_results = reader.hybrid_search("资本充足率", top_k=3)

            self.assertTrue(vector_results)
            self.assertTrue(hybrid_results)
            self.assertIn("_retrieval", hybrid_results[0].metadata)


if __name__ == "__main__":
    unittest.main()
