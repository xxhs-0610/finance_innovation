from __future__ import annotations

import unittest
from unittest.mock import patch

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
