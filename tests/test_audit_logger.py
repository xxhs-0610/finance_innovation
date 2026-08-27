"""Unit tests for Trustworthy Audit Logger and Error Attribution Trace."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.utils.audit_logger import QAFlowTrace, audit_logger, get_audit_log_path
from app.services.rag_service import rag_service


class AuditLoggerTest(unittest.TestCase):
    def test_formatted_log_contains_all_seven_sections(self) -> None:
        """Verify the log contains all 7 mandated sections: [QUERY], [ROUTER], [ANALYZER], [RETRIEVAL], [RERANK], [VERIFIER], [FINAL_ACTION]."""
        trace = QAFlowTrace(
            trace_id="trace_test_001",
            timestamp="2026-08-26 21:00:00",
            query="第三档商业银行核心一级资本充足率最低要求是多少？",
            router_intent="DOMAIN_QA",
            router_qa_type="THRESHOLD_RULE",
            router_reason="用户询问银行业监管阈值或法定比例底线",
            analyzer_keywords=["第三档商业银行", "核心一级资本充足率", "最低要求"],
            analyzer_indicator="核心一级资本充足率",
            analyzer_institution="第三档商业银行",
            analyzer_rule_type="最低监管要求",
            analyzer_topic="资本监管",
            retrieval_recall_counts={"bm25": 20, "vector": 20},
            retrieval_top_k=3,
            retrieval_sources=["《商业银行资本管理办法》附件23"],
            retrieval_status="answerable",
            rerank_results=[{"citation_id": "E1", "title": "附件23", "score": 1.85}],
            verifier_answerable=True,
            verifier_reason_code="SUFFICIENT",
            verifier_reason="证据直接明确回答了问题",
            verifier_supporting_ids=["E1"],
            final_action="ANSWER",
            final_status="answered",
            final_answer_preview="第三档商业银行核心一级资本充足率最低要求为7.5% [E1]",
            citations=["E1"],
            latency_ms={"retrieval_ms": 12, "generation_ms": 150, "total_ms": 162},
            stage_attribution="SUCCESS_ANSWERED",
            diagnostic_notes="全流程成功完成生成与核验",
        )

        formatted = trace.to_formatted_log()
        self.assertIn("[QUERY]", formatted)
        self.assertIn("[ROUTER]", formatted)
        self.assertIn("[PLAN]", formatted)
        self.assertIn("[RETRIEVAL_TASKS]", formatted)
        self.assertIn("[RETRIEVAL_RESULTS]", formatted)
        self.assertIn("[EXECUTOR]", formatted)
        self.assertIn("[INTERMEDIATE_VERIFY]", formatted)
        self.assertIn("[CALCULATION]", formatted)
        self.assertIn("[OPTION_VERIFY]", formatted)
        self.assertIn("[FINAL_VERIFY]", formatted)
        self.assertIn("[FINAL_ACTION]", formatted)

        self.assertIn("第三档商业银行", formatted)
        self.assertIn("SUFFICIENT", formatted)
        self.assertIn("ACTION: ANSWER", formatted)

    def test_infer_stage_attribution_accurately_pinpoints_failures(self) -> None:
        """Verify error attribution distinguishes router, retrieval, verifier, and generator."""
        # 1. Router out of scope
        attr1, _ = audit_logger.infer_stage_attribution("OUT_OF_SCOPE", 0, None, None, "refused", False)
        self.assertEqual(attr1, "ROUTER_OUT_OF_SCOPE")

        # 2. Retrieval empty
        attr2, _ = audit_logger.infer_stage_attribution("DOMAIN_QA", 0, None, None, "refused", False)
        self.assertEqual(attr2, "RETRIEVAL_FAILED")

        # 3. Verifier blocked
        attr3, _ = audit_logger.infer_stage_attribution("DOMAIN_QA", 3, False, "INSUFFICIENT_COVERAGE", "refused", False)
        self.assertEqual(attr3, "MISSING_EVIDENCE")

        # 4. Generator verification failed
        attr4, _ = audit_logger.infer_stage_attribution("DOMAIN_QA", 3, True, "SUFFICIENT", "refused", False)
        self.assertEqual(attr4, "GROUNDING_FAILED")

        # 5. Success
        attr5, _ = audit_logger.infer_stage_attribution("DOMAIN_QA", 3, True, "SUFFICIENT", "answered", True)
        self.assertEqual(attr5, "SUCCESS_ANSWERED")

    def test_jsonl_file_persistence(self) -> None:
        """Verify audit record is persisted as valid JSON to disk."""
        log_path = get_audit_log_path()
        trace = QAFlowTrace(
            trace_id="test_persistence_123",
            timestamp="2026-08-26 21:00:00",
            query="工商银行股票明天会不会涨？",
            router_intent="OUT_OF_SCOPE",
            final_action="REFUSE",
            final_status="refused",
        )
        audit_logger.record_trace(trace)
        self.assertTrue(log_path.exists())

        # Check last entry
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            last_json = json.loads(lines[-1])
            self.assertEqual(last_json["trace_id"], "test_persistence_123")
            self.assertEqual(last_json["final_action"], "REFUSE")


if __name__ == "__main__":
    unittest.main()
