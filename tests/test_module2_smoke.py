from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.indexing.build_kb import build_kb
from app.indexing.index_reader import KnowledgeBaseReader


class Module2SmokeTest(unittest.TestCase):
    def test_build_and_search_sample_kb(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            indexes_dir = root / "indexes"
            stats = build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=indexes_dir,
            )

            self.assertEqual(stats["clause_chunks"], 3)
            self.assertEqual(stats["table_chunks"], 3)
            self.assertTrue((processed_dir / "metadata.db").exists())
            self.assertTrue((indexes_dir / "bm25_corpus.jsonl").exists())

            reader = KnowledgeBaseReader(processed_dir / "metadata.db")
            results = reader.search("资本充足率", top_k=5)
            self.assertTrue(results)
            self.assertTrue(any(item.chunk_type == "clause" for item in results))
            self.assertTrue(any(item.chunk_type == "table" for item in results))


if __name__ == "__main__":
    unittest.main()
