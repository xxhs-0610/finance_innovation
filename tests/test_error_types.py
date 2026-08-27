"""Unit tests for Standard Error Codes and Failure Attribution (Prompt 11)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.generation.refusal import build_refusal
from app.schemas.error_schema import (
    ERROR_CODE_DESCRIPTIONS,
    ERROR_CODE_USER_MESSAGES,
    ErrorDetail,
    StandardErrorCode,
)
from app.services.rag_service import RAGService
from app.utils.audit_logger import audit_logger


class ErrorTypesTest(unittest.TestCase):
    """Test suite verifying granular standard error codes and failure attribution."""

    def setUp(self):
        self.rag_service = RAGService()

    def test_all_standard_error_codes_defined(self):
        """Verify all 9 mandatory error codes are defined with descriptions and user messages."""
        mandatory_codes = [
            "AMBIGUOUS_QUERY",
            "RETRIEVAL_FAILED",
            "MISSING_EVIDENCE",
            "MISSING_OPERAND",
            "CONFLICTING_EVIDENCE",
            "CALCULATION_FAILED",
            "OPTION_NOT_VERIFIED",
            "INSUFFICIENT_OPTIONS",
            "GROUNDING_FAILED",
        ]
        for code in mandatory_codes:
            self.assertIn(code, ERROR_CODE_DESCRIPTIONS)
            self.assertIn(code, ERROR_CODE_USER_MESSAGES)
            detail = ErrorDetail(error_code=code, stage="ROUTER")
            self.assertTrue(len(detail.message) > 0)
            self.assertTrue(len(detail.user_message) > 0)

    def test_ambiguous_query_error(self):
        """Test user ambiguous query triggers AMBIGUOUS_QUERY (not general failure)."""
        q = "这个达到监管标准了吗？"
        res = self.rag_service.ask(q)
        self.assertEqual(res["status"], "needs_clarification")
        self.assertEqual(res.get("error_code"), "AMBIGUOUS_QUERY")

    def test_missing_operand_table_error(self):
        """Test missing candidate/operand in table comparison triggers MISSING_OPERAND."""
        q = "在《2023年4季度保险业资金运用情况表》中，不存在的指标A与不存在的指标B相差多少？"
        res = self.rag_service.ask(q)
        self.assertEqual(res["status"], "no_evidence")
        self.assertEqual(res.get("error_code"), "MISSING_OPERAND")
        self.assertIn("MISSING_OPERAND", res["verification"]["issues"])

    def test_missing_evidence_error(self):
        """Test query for non-existent regulation clause returns MISSING_EVIDENCE, not clarification."""
        q = "《消费金融公司管理办法》第九百九十九条规定了什么？"
        res = self.rag_service.ask(q)
        self.assertEqual(res["status"], "no_evidence")
        self.assertIn(res.get("error_code"), ("MISSING_EVIDENCE", "RETRIEVAL_FAILED", "NO_RELEVANT_EVIDENCE"))

    def test_build_refusal_with_standard_error_codes(self):
        """Test build_refusal correctly formats distinct explanations for various error codes."""
        refusal1 = build_refusal("计算测试", error_code="CALCULATION_FAILED")
        self.assertEqual(refusal1["error_code"], "CALCULATION_FAILED")
        self.assertIn("数学计算异常", refusal1["answer"])

        refusal2 = build_refusal("选项测试", error_code="INSUFFICIENT_OPTIONS")
        self.assertEqual(refusal2["error_code"], "INSUFFICIENT_OPTIONS")
        self.assertIn("数量要求", refusal2["answer"])

        refusal3 = build_refusal("核验测试", error_code="GROUNDING_FAILED")
        self.assertEqual(refusal3["error_code"], "GROUNDING_FAILED")
        self.assertIn("事实核验", refusal3["answer"])

    def test_audit_logger_stage_attribution(self):
        """Verify audit logger distinguishes failure stages correctly."""
        code1, note1 = audit_logger.infer_stage_attribution(
            "NEED_CLARIFICATION", 0, None, None, "needs_clarification", False
        )
        self.assertEqual(code1, "AMBIGUOUS_QUERY")
        self.assertIn("ROUTER", note1)

        code2, note2 = audit_logger.infer_stage_attribution(
            "DOMAIN_QA", 5, False, "MISSING_OPERAND", "no_evidence", False
        )
        self.assertEqual(code2, "MISSING_OPERAND")
        self.assertIn("TABLE_EXECUTION", note2)

        code3, note3 = audit_logger.infer_stage_attribution(
            "DOMAIN_QA", 5, True, None, "refused", False
        )
        self.assertEqual(code3, "GROUNDING_FAILED")
        self.assertIn("POST_VERIFICATION", note3)

        code4, note4 = audit_logger.infer_stage_attribution(
            "DOMAIN_QA", 0, None, None, "no_evidence", False
        )
        self.assertEqual(code4, "RETRIEVAL_FAILED")
        self.assertIn("RETRIEVAL", note4)


if __name__ == "__main__":
    unittest.main()
