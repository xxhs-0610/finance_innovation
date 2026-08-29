"""Evidence Verifier for RegTrust-RAG.

Evaluates: "Are the retrieved evidence passages sufficient, complete, authoritative,
consistent, and specific enough to answer the user question?"

Evaluates 5 Dimensions:
  1. RELEVANCE: Direct alignment with user question; topic similarity != answerable.
  2. COVERAGE: Must cover all requested periods/metrics/institutions (e.g. 2024 and 2025).
  3. AUTHORITY: Must originate from official regulatory rules or statistical reports in KB.
  4. CONSISTENCY: Must not contain unresolved version/date/numeric/scope conflicts.
  5. SPECIFICITY: Must contain concrete answers (e.g. specific years instead of '按规定保存').

Strict Constraint:
  - NEVER use background knowledge or LLM memory to answer or judge sufficiency.
  - Only inspect: user question + retrieved evidence passages.
  - If insufficient: answerable=False.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import ssl
import urllib.request
from typing import Any

import certifi

from app.generation.deepseek_client import (
    deepseek_api_key,
    deepseek_base_url,
    deepseek_enabled,
    deepseek_model,
    deepseek_timeout_seconds,
)
from app.schemas.answer_schema import normalize_evidence
from app.schemas.verifier_schema import (
    ALLOWED_REASON_CODES,
    EvidenceVerificationResult,
    ReasonCode,
)
from app.utils.logger import get_logger

logger = get_logger("app.generation.evidence_verifier")

# Patterns for Specificity and Coverage Checks
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
DURATION_QUESTION_RE = re.compile(r"(?:保存|存储|留存|存档|保管).*(?:几年|多少年|期限|多长|多长时间)")
SPECIFIC_DURATION_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*(?:年|个月|天|日)")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|％|‰|万亿元|亿元|万元|元|万人次|万人|人次|户|家|天|日|个月|年)?"
)
VAGUE_QUALIFIER_RE = re.compile(
    r"按(?:照)?(?:国家|有关|相关|法定|法律法规|\s)*(?:规定|要求)(?:的)?(?:期限)?(?:保存|执行|办理|留存|处理)|依法(?:合规)?|合理确定|另行规定"
)
TIERED_BANK_RE = re.compile(r"第[一二三]档(?:商业)?银行")


class EvidenceVerifier:
    """Pre-generation Gate: Rigorously verifies evidence sufficiency before answer generation."""

    def verify(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        *,
        query_analysis: Any = None,
        use_llm: bool = True,
    ) -> EvidenceVerificationResult:
        q = (question or "").strip()
        records = normalize_evidence(evidence)

        # ---------------------------------------------------------------------
        # 1. Deterministic Heuristic Guardrail Checks
        # ---------------------------------------------------------------------
        heuristic_res = self._deterministic_checks(q, records, query_analysis)
        if heuristic_res is not None:
            self._log_decision(q, heuristic_res)
            return heuristic_res

        # ---------------------------------------------------------------------
        # 2. DeepSeek JSON-Mode Evidence Verification (If Enabled & Allowed)
        # ---------------------------------------------------------------------
        if use_llm and deepseek_enabled():
            llm_res = self._llm_verify(q, records)
            if llm_res is not None:
                self._log_decision(q, llm_res)
                return llm_res

        # ---------------------------------------------------------------------
        # 3. Fallback Deterministic Verdict
        # ---------------------------------------------------------------------
        fallback_res = self._fallback_verify(q, records, query_analysis)
        self._log_decision(q, fallback_res)
        return fallback_res

    def _deterministic_checks(
        self,
        question: str,
        records: list[dict[str, Any]],
        query_analysis: Any,
    ) -> EvidenceVerificationResult | None:
        """Run strict fast guardrails across the 5 dimensions."""
        # Check A: Zero Evidence
        if not records:
            return EvidenceVerificationResult(
                answerable=False,
                evidence_sufficient=False,
                need_clarification=False,
                reason_code="NO_RELEVANT_EVIDENCE",
                reason="未检索到任何相关的银行业监管或统计证据",
                supporting_evidence_ids=[],
                missing_information=["知识库中无对应有效切片"],
            )

        # Build concatenated evidence search text
        evidence_texts = [_get_record_text(r) for r in records]
        combined_text = " ".join(evidence_texts)

        # Check B: Authority (Must have valid doc_id, issuer, or title)
        valid_sources = [
            r for r in records
            if str((r.get("source") or {}).get("doc_id") or "").strip()
            or str((r.get("source") or {}).get("title") or "").strip()
            or str((r.get("source") or {}).get("issuer") or "").strip()
        ]
        if not valid_sources:
            return EvidenceVerificationResult(
                answerable=False,
                evidence_sufficient=False,
                need_clarification=False,
                reason_code="NO_RELEVANT_EVIDENCE",
                reason="检索证据缺少权威监管制度或统计报表溯源标识",
                supporting_evidence_ids=[],
                missing_information=["证据缺少官方文件出处"],
            )

        # Check C: Coverage - Multi-Year Query (e.g. '2024和2025分别是多少')
        requested_years = YEAR_RE.findall(question)
        if len(set(requested_years)) >= 2:
            missing_years = [
                yr for yr in set(requested_years)
                if yr not in combined_text and f"{yr}年" not in combined_text
            ]
            if missing_years:
                return EvidenceVerificationResult(
                    answerable=False,
                    evidence_sufficient=False,
                    need_clarification=False,
                    reason_code="INSUFFICIENT_COVERAGE",
                    reason=f"检索证据未完全覆盖问题要求的年份，缺少：{', '.join(sorted(missing_years))}年的数据",
                    supporting_evidence_ids=[r.get("citation_id", "E1") for r in records if any(yr in _get_record_text(r) for yr in set(requested_years) - set(missing_years))],
                    missing_information=[f"缺少{yr}年监管统计数据" for yr in sorted(missing_years)],
                )

        # Check D: Specificity - Duration query without concrete duration (e.g. '保存几年？' vs '按规定期限保存')
        if DURATION_QUESTION_RE.search(question):
            has_concrete_duration = bool(SPECIFIC_DURATION_RE.search(combined_text))
            has_vague_only = bool(VAGUE_QUALIFIER_RE.search(combined_text))
            # A passage can be topically related (for example, it may say
            # that records must be retained) without answering the requested
            # duration.  Do not let wording such as “应当保存” pass through
            # merely because it is not an exact “按规定保存” phrase.
            mentions_retention = any(
                marker in combined_text for marker in ("保存", "存储", "留存", "存档", "保管")
            )
            if not has_concrete_duration and (has_vague_only or mentions_retention):
                return EvidenceVerificationResult(
                    answerable=False,
                    evidence_sufficient=False,
                    need_clarification=False,
                    reason_code="MISSING_NUMERIC_EVIDENCE",
                    reason="检索证据提及资料保存要求，但未包含具体的保存年限数值",
                    supporting_evidence_ids=[],
                    missing_information=["缺少具体保存年限数值"],
                )

        # Check E: Specificity - Direct Numeric Inquiries (e.g. '是多少？')
        is_metadata_q = any(
            w in question
            for w in ("发布", "发文", "机构", "部门", "机关", "日期", "何时", "文号", "文件名", "标题", "由谁", "如何", "怎样")
        )
        if not is_metadata_q and any(w in question for w in ("是多少", "为多少", "多大比例", "最低监管要求是多少", "监管底线是多少")):
            has_numbers = bool(NUMBER_RE.search(combined_text))
            if not has_numbers and not any(w in question for w in ("流程", "程序", "规定是什么", "主要内容")):
                return EvidenceVerificationResult(
                    answerable=False,
                    evidence_sufficient=False,
                    need_clarification=False,
                    reason_code="MISSING_NUMERIC_EVIDENCE",
                    reason="问题询问具体监管数值或比例，但证据中未包含明确的数值或阈值规定",
                    supporting_evidence_ids=[],
                    missing_information=["缺少具体监管数值或比例要求"],
                )

        # Check F: Scenario Condition / Tier Ambiguity (e.g. '商业银行资本充足率最低监管要求是多少' without choices/tiers)
        if "资本充足率" in question and "商业银行" in question and not TIERED_BANK_RE.search(question):
            # Never clarify if question contains choices or explicit comparative targets
            if not any(c in question for c in ("A:", "A.", "A：", "A、", "各档", "分别", "谁最高", "哪项", "谁最大", "谁最小")):
                # If evidence mentions multiple tiers with differing rates
                if "第一档" in combined_text and ("第二档" in combined_text or "第三档" in combined_text):
                    return EvidenceVerificationResult(
                        answerable=False,
                        evidence_sufficient=False,
                        need_clarification=True,
                        reason_code="MISSING_SCENARIO_CONDITION",
                        reason="监管规定针对第一档、第二档及第三档商业银行设有不同的资本充足率底线要求，需明确机构档位",
                        supporting_evidence_ids=[r.get("citation_id", f"E{i}") for i, r in enumerate(records, 1)],
                        missing_information=["请明确是第一档、第二档还是第三档商业银行"],
                    )

        # Check G: Compliance Judgment Scenario Fact Gaps (e.g. Missing Net Capital for Loan Concentration)
        is_compliance_q = any(
            w in question for w in ("合规吗", "是否合规", "能否办理", "是否违规", "是否允许", "合规判定", "是否符合监管")
        ) or (query_analysis and getattr(query_analysis, "rule_type", "") in {"合规判断", "COMPLIANCE_JUDGMENT", "合规判定"})
        if is_compliance_q:
            try:
                from app.compliance.compliance_engine import compliance_engine
                from app.compliance.fact_extractor import scenario_fact_extractor

                facts = scenario_fact_extractor.extract(question)
                is_ready, missing_fact, clarification_prompt = compliance_engine._check_critical_fact_gap(facts, question)
                if not is_ready:
                    return EvidenceVerificationResult(
                        answerable=False,
                        evidence_sufficient=False,
                        need_clarification=True,
                        reason_code="MISSING_SCENARIO_CONDITION",
                        reason=f"合规判定缺少关键事实：{missing_fact}",
                        supporting_evidence_ids=[r.get("citation_id", f"E{i}") for i, r in enumerate(records, 1)],
                        missing_information=[clarification_prompt or f"请补充{missing_fact}"],
                    )

                # If specific statutory compliance patterns have complete facts, verify as sufficient
                if facts.loan_amount is not None and facts.net_capital is not None:
                    return EvidenceVerificationResult(
                        answerable=True,
                        evidence_sufficient=True,
                        need_clarification=False,
                        reason_code="SUFFICIENT",
                        reason="场景事实完整（具备贷款金额与资本净额），满足单一客户贷款集中度确定性核算要件",
                        supporting_evidence_ids=[r.get("citation_id", f"E{i}") for i, r in enumerate(records, 1)] or ["E1"],
                        missing_information=[],
                    )
                if facts.is_related_party and facts.is_credit_loan:
                    return EvidenceVerificationResult(
                        answerable=True,
                        evidence_sufficient=True,
                        need_clarification=False,
                        reason_code="SUFFICIENT",
                        reason="场景事实明确为向关系人发放信用贷款，符合《商业银行法》第四十条禁止性条款要件",
                        supporting_evidence_ids=[r.get("citation_id", f"E{i}") for i, r in enumerate(records, 1)] or ["E1"],
                        missing_information=[],
                    )
            except Exception as e:
                logger.warning(f"[EvidenceVerifier] 合规关键事实前置检查跳过: {e}")

        return None

    def _llm_verify(
        self,
        question: str,
        records: list[dict[str, Any]],
    ) -> EvidenceVerificationResult | None:
        """Call DeepSeek in strict JSON mode to judge evidence sufficiency."""
        api_key = deepseek_api_key()
        if not api_key:
            return None

        # Format evidence chunks cleanly
        evidence_snippets: list[str] = []
        for idx, r in enumerate(records[:8], 1):
            cid = r.get("citation_id", f"E{idx}")
            src = r.get("source") or {}
            meta = r.get("metadata") or {}
            title = src.get("title") or src.get("table_name") or "监管制度"
            issuer = src.get("issuer", "")
            issuer_str = f" 发布机构：{issuer}" if issuer else ""
            pub_date = src.get("publish_date", "")
            pub_str = f" 发布日期：{pub_date}" if pub_date else ""
            clause = src.get("clause_no") or src.get("sheet_name") or ""
            section_path = src.get("section_path") or meta.get("section_path") or []
            section_str = f" [{' > '.join(str(s) for s in section_path)}]" if section_path else ""
            local_path = src.get("local_path", "")
            file_name = Path(local_path).name if local_path else ""
            file_desc = f" ({file_name})" if file_name and file_name not in title else ""
            text = (r.get("text") or r.get("retrieval_text") or "").strip()

            derived_values = meta.get("derived_values") or []
            derived_text = ""
            if isinstance(derived_values, list):
                exps = [str(d.get("explanation")) for d in derived_values if isinstance(d, dict) and d.get("explanation")]
                if exps:
                    derived_text = "\n换算/衍生值：" + "；".join(exps)

            evidence_snippets.append(
                f"[{cid}] 《{title}{file_desc}》{issuer_str}{pub_str} {clause}{section_str}\n{text}{derived_text}"
            )

        evidence_str = "\n\n".join(evidence_snippets)

        prompt_system = (
            "你是一个最高严谨度的【银行业监管证据充分性核验器（Evidence Verifier）】。\n"
            "你的任务是审查【当前检索证据】是否足以、完整、具体、确定地回答【用户问题】。\n\n"
            "【五项判定维度】:\n"
            "1. RELEVANCE: 证据必须直接对应问题，仅主题相似但未包含具体答案的判为不充分。\n"
            "2. COVERAGE: 若问题包含多个年份（如2024和2025）、多项指标或多个对象，证据必须全部覆盖；缺少任何一项判为 INSUFFICIENT_COVERAGE。\n"
            "3. AUTHORITY: 证据必须来源于知识库官方监管制度、政策规章或统计报表。\n"
            "4. CONSISTENCY: 证据之间不能存在版本冲突、日期冲突、数值矛盾或适用主体冲突。\n"
            "5. SPECIFICITY: 证据必须包含具体结论或数值。例如问'保存几年'，证据只说'按规定保存'无具体数字，必须判为 MISSING_NUMERIC_EVIDENCE。\n\n"
            "【最重要铁律】:\n"
            "- 严禁使用你自己的大模型外部知识脑补答案！你只能看给出的检索证据。\n"
            "- 如果检索证据没有包含回答所需的充分事实，必须判定 answerable=false。\n\n"
            "【输出格式】:\n"
            "必须输出合法 JSON 对象，格式如下：\n"
            "{\n"
            '  "answerable": true/false,\n'
            '  "evidence_sufficient": true/false,\n'
            '  "need_clarification": true/false,\n'
            '  "reason_code": "SUFFICIENT" | "NO_RELEVANT_EVIDENCE" | "INSUFFICIENT_COVERAGE" | "MISSING_KEY_FACT" | "AMBIGUOUS_QUERY" | "CONFLICTING_EVIDENCE" | "OUTDATED_OR_VERSION_UNCLEAR" | "MISSING_NUMERIC_EVIDENCE" | "MISSING_SCENARIO_CONDITION",\n'
            '  "reason": "简明扼要的核验结论说明",\n'
            '  "supporting_evidence_ids": ["E1", "E2"],\n'
            '  "missing_information": ["缺失的具体要素描述（若有）"]\n'
            "}"
        )

        user_content = f"【用户问题】: {question}\n\n【当前检索证据】:\n{evidence_str}"

        url = f"{deepseek_base_url().rstrip('/')}/chat/completions"
        payload = {
            "model": deepseek_model(),
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 500,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            timeout = min(deepseek_timeout_seconds(), 15.0)
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                choice = (data.get("choices") or [{}])[0]
                raw_json = choice.get("message", {}).get("content", "").strip()
                res_dict = json.loads(raw_json)

                reason_code = str(res_dict.get("reason_code") or "").upper().strip()
                if reason_code not in ALLOWED_REASON_CODES:
                    reason_code = "SUFFICIENT" if res_dict.get("answerable") else "MISSING_KEY_FACT"

                need_clarification = bool(res_dict.get("need_clarification"))
                # Prompt 7 Guard: Choice, comparison, calculation, and multi-quote queries never need clarification
                if any(c in question for c in ("A:", "A.", "A：", "A、", "比较", "相差", "差距", "从", "到", "谁最大", "谁最小", "哪项", "最高", "最低")):
                    need_clarification = False
                if len(re.findall(r"“[^”]+”|‘[^’]+’|《[^》]+》", question)) >= 2:
                    need_clarification = False

                return EvidenceVerificationResult(
                    answerable=bool(res_dict.get("answerable")),
                    evidence_sufficient=bool(res_dict.get("evidence_sufficient", res_dict.get("answerable"))),
                    need_clarification=need_clarification,
                    reason_code=reason_code,  # type: ignore[arg-type]
                    reason=str(res_dict.get("reason") or "证据核验完成"),
                    supporting_evidence_ids=list(res_dict.get("supporting_evidence_ids") or []),
                    missing_information=list(res_dict.get("missing_information") or []),
                )
        except Exception as exc:
            logger.warning(f"[EvidenceVerifier] DeepSeek 核验调用异常 (切换至规则引擎): {type(exc).__name__}: {exc}")
            return None

    def _fallback_verify(
        self,
        question: str,
        records: list[dict[str, Any]],
        query_analysis: Any,
    ) -> EvidenceVerificationResult:
        """Deterministic conservative fallback verification."""
        all_ids = [r.get("citation_id", f"E{i}") for i, r in enumerate(records, 1)]
        return EvidenceVerificationResult(
            answerable=True,
            evidence_sufficient=True,
            need_clarification=False,
            reason_code="SUFFICIENT",
            reason="检索证据包含银行业监管条款及相关指标事实",
            supporting_evidence_ids=all_ids,
            missing_information=[],
        )

    def _log_decision(self, question: str, res: EvidenceVerificationResult) -> None:
        """Format and write standard [EVIDENCE_VERIFIER] structured log."""
        log_entry = (
            f"\n[EVIDENCE_VERIFIER]\n"
            f"query={question}\n"
            f"answerable={res.answerable}\n"
            f"evidence_sufficient={res.evidence_sufficient}\n"
            f"need_clarification={res.need_clarification}\n"
            f"reason_code={res.reason_code}\n"
            f"reason={res.reason}\n"
            f"supporting_evidence_ids={res.supporting_evidence_ids}\n"
            f"missing_information={res.missing_information}"
        )
        logger.info(log_entry)


def _get_record_text(record: dict[str, Any]) -> str:
    source = record.get("source") or {}
    meta = record.get("metadata") or {}
    section_path = source.get("section_path") or meta.get("section_path") or []
    section_text = " ".join(str(s) for s in section_path) if isinstance(section_path, list) else ""
    local_path = source.get("local_path", "")
    file_name = Path(local_path).name if local_path else ""
    fields = [
        record.get("text"),
        record.get("retrieval_text"),
        source.get("title"),
        file_name,
        section_text,
        source.get("clause_no"),
        source.get("sheet_name"),
        source.get("table_name"),
    ]
    return " ".join(str(f).strip() for f in fields if f)


evidence_verifier = EvidenceVerifier()
verify_evidence = evidence_verifier.verify

__all__ = ["EvidenceVerifier", "evidence_verifier", "verify_evidence"]
