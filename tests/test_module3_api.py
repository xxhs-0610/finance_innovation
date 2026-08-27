from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient

from app.api.main import app


class Module3APITest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["service"], "RegTrust-RAG Engine")
        self.assertEqual(response.json()["pipeline"], "Module 1-4 Connected")

    def test_stats_and_indexes_endpoints(self) -> None:
        stats_resp = self.client.get("/api/v1/stats")
        self.assertEqual(stats_resp.status_code, 200)
        stats = stats_resp.json()
        self.assertIn("chunk_count", stats)
        self.assertIn("clause_chunk_count", stats)
        self.assertIn("table_chunk_count", stats)
        self.assertIn("embedding_dimension", stats)
        self.assertEqual(stats["embedding_dimension"], 512)

        indexes_resp = self.client.get("/api/v1/kb/indexes")
        self.assertEqual(indexes_resp.status_code, 200)
        idx_data = indexes_resp.json()
        self.assertIn("summary", idx_data)
        self.assertIn("files", idx_data)
        self.assertEqual(idx_data["summary"]["embedding_dimension"], 512)

        verify_resp = self.client.post("/api/v1/kb/indexes/verify")
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()
        self.assertTrue(verify_data["passed"])
        self.assertEqual(verify_data["dimension"], 512)

    @patch("app.api.main.retrieve")
    def test_retrieve_endpoint_preserves_module3_contract(self, mocked_retrieve) -> None:
        class FakeResponse:
            def to_dict(self):
                return {
                    "query": "资本充足率",
                    "status": "answerable",
                    "analysis": {"query_type": "table_lookup"},
                    "evidence": [{"chunk_id": "chunk-1"}],
                    "diagnostics": {"failures": []},
                    "module4_guidance": {
                        "action": "answer",
                        "may_generate_answer": True,
                    },
                }

        mocked_retrieve.return_value = FakeResponse()
        response = self.client.post(
            "/api/v1/retrieve",
            json={"question": "资本充足率", "top_k": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "answerable")
        self.assertTrue(response.json()["module4_guidance"]["may_generate_answer"])
        mocked_retrieve.assert_called_once_with("资本充足率", top_k=3)

    def test_retrieve_endpoint_rejects_blank_question(self) -> None:
        response = self.client.post(
            "/api/v1/retrieve",
            json={"question": "   "},
        )
        self.assertEqual(response.status_code, 422)

    def test_retrieve_endpoint_rejects_invalid_top_k(self) -> None:
        response = self.client.post(
            "/api/v1/retrieve",
            json={"question": "资本充足率", "top_k": 0},
        )
        self.assertEqual(response.status_code, 422)

    @patch("app.api.main.retrieve", side_effect=RuntimeError("backend failed"))
    def test_retrieve_endpoint_hides_internal_error_details(self, _mocked) -> None:
        response = self.client.post(
            "/api/v1/retrieve",
            json={"question": "资本充足率"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            {
                "code": "retrieval_unavailable",
                "error_type": "RuntimeError",
            },
        )
        self.assertNotIn("backend failed", response.text)


if __name__ == "__main__":
    unittest.main()
