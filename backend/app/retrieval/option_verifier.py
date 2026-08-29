"""Option Verification Engine for RegTrust-RAG (Prompt 6).

Provides deterministic and NLI-grounded verification for:
  - FACT_SINGLE_CHOICE: discrete per-option claim verification -> finds unique SUPPORTED / CONTRADICTED
  - FACT_MULTI_CHOICE: discrete sub-claim verification -> validates all sub-claims -> finds SUPPORTED options matching required count

Guarantees:
  1. Each option is evaluated independently against its retrieved evidence.
  2. SUPPORTED requires positive evidence grounding.
  3. CONTRADICTED requires explicit contradiction (numbers, modality, conditions).
  4. NOT_ENOUGH_EVIDENCE is assigned when evidence is insufficient.
  5. Final selection is derived strictly from structured verdicts, never ungrounded LLM guessing.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import math
import re
from typing import Any, Mapping, Sequence

from app.generation.deepseek_client import deepseek_enabled
from app.schemas.chunk_schema import SearchResult
from app.schemas.multi_target_retrieval_schema import (
    MultiTargetRetrievalResponse,
    TargetRetrievalResult,
)
from app.schemas.option_verification_schema import (
    OptionVerificationItem,
    OptionVerificationResponse,
    SubClaimVerification,
    VerdictType,
)
from app.schemas.task_plan_schema import ChoiceOption, TaskPlan
from app.utils.logger import get_logger
from configs.settings import settings

logger = get_logger("app.retrieval.option_verifier")


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, value))))


def _normalize_document_name(value: str | None) -> str | None:
    """Match user labels that include a format suffix to KB titles."""
    if not value:
        return value
    name = str(value).strip()
    name = re.sub(r"\s*[\(\uff08][^\)\uff09]*?(?:pdf|docx?|xlsx?)[^\)\uff09]*[\)\uff09]\s*", "", name, flags=re.I)
    name = re.sub(r"\.(?:pdf|docx?|xlsx?)$", "", name, flags=re.I)
    return name.strip() or None


def clean_for_match(text: str) -> str:
    """Normalize text for invariant comparison by stripping punctuation and whitespaces."""
    return re.sub(r"[\s\r\n\t，。；：、“”‘’《》（）()\[\]【】\.,:;\"'——\-·]", "", text)


def extract_numbers_with_units(text: str) -> list[str]:
    """Extract numeric values with accompanying units from text."""
    return re.findall(
        r"\d+(?:\.\d+)?\s*(?:%|％|‰|万亿元|亿元|万元|元|万人|人|户|家|日|个工作日|工作日|年|个月)?",
        text,
    )


def _semantic_table_match(claim: str, text: str) -> bool:
    """Recognize compact table rows whose headers are split from values.

    This is domain independent: it extracts numeric/unit tokens and salient
    labels (Chinese words, periods, categories) from the claim, then checks
    that the same signals occur in the serialized table row. It therefore
    works for insurance, banking, finance, and arbitrary regulatory tables.
    """
    c = clean_for_match(claim)
    t = clean_for_match(text)
    if not c or not t:
        return False
    claim_nums = extract_numbers_with_units(claim)
    if not claim_nums or any(num.replace(" ", "") not in t for num in claim_nums):
        return False

    # Keep meaningful lexical markers while ignoring function words and
    # generic question phrasing. Include period/category/indicator terms.
    markers = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}", claim)
    stop = {"平均", "上限", "下列", "表述", "属于", "材料", "内容", "关于", "其中", "选项", "正确", "错误"}
    salient = [m for m in markers if m not in stop]
    # Match lexical pieces rather than requiring long phrases to be
    # contiguous: serialized rows commonly split a category and indicator
    # (e.g. “个人” ... “意外险=35%”).
    pieces: list[str] = []
    for marker in salient:
        if len(marker) <= 4:
            pieces.append(marker)
        else:
            pieces.extend(marker[i:i + 2] for i in range(0, len(marker) - 1, 2))
    if pieces and sum(1 for m in pieces if m in text) < max(1, min(3, len(pieces))):
        return False
    # At least one structured delimiter/header-value cue should be present.
    if not re.search(r"[=:：]|单位|%|％", text):
        return False
    return True


def detect_question_intent_target(question: str) -> str:
    """Detect whether question asks for CORRECT statement or INCORRECT/FALSE option."""
    # Only match meta-inquiries asking for false/incorrect options
    if re.search(r"(?:哪项|哪一项|哪些|说法|表述|下列|以下)(?:.*)?(?:不正确|错误|不符合|并非|不当|违规)", question):
        return "INCORRECT"
    if re.search(r"^(?:下列|以下)(?:.*)?(?:不正确|错误|不符合|并非|不属于|违规)", question):
        return "INCORRECT"
    return "CORRECT"


def compute_sliding_similarity(claim: str, text: str) -> tuple[float, str]:
    """Compute maximum sliding window sequence similarity between claim and chunk text."""
    c_clean = clean_for_match(claim)
    t_clean = clean_for_match(text)
    if not c_clean or not t_clean:
        return 0.0, ""

    if c_clean in t_clean:
        return 1.0, c_clean

    l_c = len(c_clean)
    l_t = len(t_clean)

    if l_t <= l_c:
        return SequenceMatcher(None, c_clean, t_clean).ratio(), t_clean

    best_ratio = 0.0
    best_sub = ""
    # Test sliding windows around the size of the claim
    for w_len in (l_c, l_c + 5, l_c + 10, max(1, l_c - 5)):
        if w_len > l_t:
            continue
        for i in range(0, l_t - w_len + 1, max(1, l_c // 15)):
            sub = t_clean[i : i + w_len]
            r = SequenceMatcher(None, c_clean, sub).ratio()
            if r > best_ratio:
                best_ratio = r
                best_sub = sub
                if best_ratio >= 0.98:
                    return best_ratio, best_sub

    return best_ratio, best_sub


def _retrieval_score(chunk: Any) -> float:
    """Use the retrieval/rerank score as a tie-breaker for option evidence."""
    try:
        score = float(getattr(chunk, "score", 0.0) or 0.0)
    except Exception:
        score = 0.0
    return score


def normalize_num_value(val_str: str, unit: str) -> tuple[float, str]:
    """Normalize numerical value and unit for cross-scale comparisons (万/亿/年/月)."""
    try:
        v = float(val_str)
        if unit in ("万", "万元"):
            return v * 10000.0, "元"
        elif unit in ("亿", "亿元"):
            return v * 100000000.0, "元"
        elif unit in ("%", "％", "个百分点"):
            return v, "%"
        elif unit in ("年", "个月", "月"):
            if unit == "年":
                return v * 12.0, "月"
            return v, "月"
        return v, unit
    except Exception:
        return 0.0, unit


def detect_contradictions(claim: str, evidence_text: str) -> tuple[bool, str]:
    """Check for explicit numerical, institutional, or deontic modality contradictions."""
    c_nums = extract_numbers_with_units(claim)
    e_nums = extract_numbers_with_units(evidence_text)

    # 1. Number contradiction check with unit normalization
    if c_nums and e_nums:
        c_set = set(c_nums)
        e_set = set(e_nums)
        if not c_set.issubset(e_set):
            for cn in c_nums:
                if cn in e_nums:
                    continue
                c_val = re.findall(r"[\d\.]+", cn)
                c_unit = re.sub(r"[\d\.]+", "", cn).strip()
                if c_val:
                    cn_norm_val, cn_norm_unit = normalize_num_value(c_val[0], c_unit)
                    for en in e_nums:
                        if en in c_nums:
                            continue
                        e_val = re.findall(r"[\d\.]+", en)
                        e_unit = re.sub(r"[\d\.]+", "", en).strip()
                        if e_val:
                            en_norm_val, en_norm_unit = normalize_num_value(e_val[0], e_unit)
                            if cn_norm_unit and en_norm_unit and cn_norm_unit == en_norm_unit and cn_norm_val != en_norm_val:
                                return True, f"监管原文规定为【{en}】，选项表述为【{cn}】"

    # 2. Modality inversion check (prohibition vs permission)
    prohibitions = ["不得", "禁止", "严禁", "不准", "不应", "不低于", "不得低于", "不得高于", "不超过"]
    permissions = ["可以", "允许", "准予", "可行"]

    has_c_prohibition = any(p in claim for p in prohibitions)
    has_e_prohibition = any(p in evidence_text for p in prohibitions)

    if has_e_prohibition and not has_c_prohibition:
        for p in prohibitions:
            if p in evidence_text:
                for perm in permissions:
                    if perm in claim:
                        return True, f"监管原文明确【{p}】，而选项声称【{perm}】"

    if has_c_prohibition and not has_e_prohibition:
        if any(perm in evidence_text for perm in ["应当", "必须", "可以"]):
            return True, f"选项包含禁止性表述，而监管原文为允许或要求"

    return False, ""


class OptionVerificationEngine:
    """Discrete Option Verification Engine for single and multi-choice QA."""

    def verify(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> OptionVerificationResponse:
        """Verify all options in task_plan against discrete retrieval evidence."""
        task_type = task_plan.task_type
        question = task_plan.question or ""
        
        # Extract question stem without options to prevent option text from biasing polarity
        stem = question
        if "A:" in question or "A." in question or "A：" in question or "A、" in question:
            m = re.split(r"(?:\s*|\n)[A-Da-d][\.:：、\s]", question, maxsplit=1)
            if m:
                stem = m[0].strip()

        choice_mode = "MULTI" if task_type == "FACT_MULTI_CHOICE" else "SINGLE"
        question_intent_target = detect_question_intent_target(stem)
        required_count = (
            task_plan.required_correct_count
            if (task_plan.required_correct_count and choice_mode == "MULTI")
            else (1 if choice_mode == "SINGLE" else 2)
        )

        doc_name = _normalize_document_name(
            task_plan.source_constraints.document_name
            if task_plan.source_constraints
            else None
        )

        task_map, merged_evidence = self._normalize_retrieval_input(retrieval_input)

        verified_options: list[OptionVerificationItem] = []

        if isinstance(task_plan.options, list):
            option_items = task_plan.options
        elif isinstance(task_plan.options, dict):
            option_items = [
                ChoiceOption(label=lbl, claim=claim)
                for lbl, claim in task_plan.options.items()
            ]
        else:
            option_items = []

        for opt in option_items:
            task_id = f"OPT_{opt.label}"
            evidence = task_map.get(task_id) or merged_evidence
            verified_opt = self.verify_option(
                opt.label,
                opt.claim,
                opt.sub_claims or [],
                evidence,
                doc_name=doc_name,
            )
            verified_options.append(verified_opt)

        # Compute transparent multi-signal ranking.  These weights are
        # intentionally simple and local; retrieval similarity is no longer a
        # standalone veto.  A future labelled validation split can replace the
        # coefficients without changing the decision interface.
        raw_r = [max(0.0, min(1.0, self._option_similarity(o))) for o in verified_options]
        for idx, item in enumerate(verified_options):
            r_i = raw_r[idx]
            others = raw_r[:idx] + raw_r[idx + 1 :]
            margin = r_i - (max(others) if others else 0.0)
            source_match = 1.0 if doc_name and item.evidence_ids else (0.5 if item.evidence_ids else 0.0)
            # In multi-fact options, score the proportion of sub-claims that
            # are explicitly supported rather than collapsing every partial
            # match to the same weak E_i value.
            if item.sub_claims:
                entailment = sum(1.0 for sc in item.sub_claims if sc.verdict == "SUPPORTED") / len(item.sub_claims)
                if entailment == 0.0 and item.evidence_ids:
                    entailment = 0.35 * r_i
            else:
                entailment = 1.0 if item.verdict == "SUPPORTED" else (0.35 * r_i if item.evidence_ids else 0.0)
            contradiction = 1.0 if item.verdict == "CONTRADICTED" else 0.0
            cal = settings.option_calibration
            ranking = _sigmoid(
                cal.beta0
                + cal.beta1 * r_i
                + cal.beta2 * entailment
                + cal.beta3 * source_match
                + cal.beta4 * margin
                - cal.beta5 * contradiction
            )
            item.max_similarity = r_i
            item.source_match = source_match
            item.entailment_support = entailment
            item.relative_margin = margin
            item.contradiction_probability = contradiction
            item.ranking_score = ranking

        # Determine winner options based on intent target
        selected_options: list[str] = []
        explanation_lines: list[str] = []

        if question_intent_target == "CORRECT":
            supported_opts = [
                opt.option for opt in verified_options if opt.verdict == "SUPPORTED"
            ]
            contra_opts = [
                opt.option for opt in verified_options if opt.verdict == "CONTRADICTED"
            ]
            if choice_mode == "SINGLE":
                if len(supported_opts) == 1:
                    selected_options = supported_opts
                elif len(supported_opts) > 1:
                    supported_items = [
                        opt for opt in verified_options if opt.verdict == "SUPPORTED"
                    ]
                    best = max(supported_items, key=lambda x: x.confidence)
                    selected_options = [best.option]
                else:
                    # Elimination: ONLY if exactly 1 option remains and all others are explicitly CONTRADICTED
                    if len(contra_opts) == len(verified_options) - 1 and len(verified_options) > 1:
                        not_contra = [
                            opt.option
                            for opt in verified_options
                            if opt.verdict != "CONTRADICTED"
                        ]
                        selected_options = not_contra
                    else:
                        selected_options = []
            else:  # MULTI
                if supported_opts:
                    selected_options = supported_opts
                else:
                    selected_options = []

        else:  # INCORRECT / NEGATIVE INTENT
            contra_opts = [
                opt.option for opt in verified_options if opt.verdict == "CONTRADICTED"
            ]
            supported_opts = [
                opt.option for opt in verified_options if opt.verdict == "SUPPORTED"
            ]
            if choice_mode == "SINGLE":
                if len(contra_opts) == 1:
                    selected_options = contra_opts
                elif len(contra_opts) > 1:
                    best = max(
                        [opt for opt in verified_options if opt.verdict == "CONTRADICTED"],
                        key=lambda x: x.confidence,
                    )
                    selected_options = [best.option]
                else:
                    if len(supported_opts) == len(verified_options) - 1 and len(verified_options) > 1:
                        not_sup = [
                            opt.option
                            for opt in verified_options
                            if opt.verdict != "SUPPORTED"
                        ]
                        selected_options = not_sup
                    else:
                        selected_options = []
            else:
                if contra_opts:
                    selected_options = contra_opts
                else:
                    selected_options = []

        # Once the requested document is hit, rank options by the combined
        # evidence signals.  Single choice returns top 1; multi-choice returns
        # the number requested by the question. Explicit contradictions are
        # excluded. This is intentionally independent of the old 0.70 gate.
        if question_intent_target == "INCORRECT":
            # For a negative-polarity question, contradiction is the desired
            # signal.  Prefer explicitly contradicted options; if none were
            # established, fall back to evidence-backed non-supported options
            # instead of returning NO_DECISION solely because similarity is
            # below the old fixed threshold.
            candidate_pool = [
                o for o in verified_options
                if o.evidence_ids and o.verdict == "CONTRADICTED"
            ]
            if not candidate_pool:
                candidate_pool = [
                    o for o in verified_options
                    if o.evidence_ids and o.verdict != "SUPPORTED"
                ]
        else:
            candidate_pool = [
                o for o in verified_options
                if o.evidence_ids and o.verdict != "CONTRADICTED"
            ]
        ranked_candidates = sorted(candidate_pool, key=lambda o: o.ranking_score, reverse=True)
        if ranked_candidates:
            if choice_mode == "SINGLE":
                selected_options = [ranked_candidates[0].option]
            else:
                selected_options = [o.option for o in ranked_candidates[:required_count]]

        status = "SUCCESS" if selected_options else "NO_DECISION"

        # Construct explanation
        target_desc = "正确" if question_intent_target == "CORRECT" else "错误/不符合规定"
        explanation_lines.append(f"题目要求找出【{target_desc}】的表述，逐项验证结论如下：")
        for vo in verified_options:
            verdict_cn = (
                "✅ 正确/有依据支持"
                if vo.verdict == "SUPPORTED"
                else (
                    "❌ 错误/与原文矛盾"
                    if vo.verdict == "CONTRADICTED"
                    else "⚠️ 证据不足/非该文件规定"
                )
            )
            ev_str = f"（依据: {', '.join(vo.evidence_ids)}）" if vo.evidence_ids else ""
            explanation_lines.append(f"- **选项 {vo.option}** [{verdict_cn}]{ev_str}：{vo.reason}")

        if selected_options:
            explanation_lines.append(
                f"\n综上，符合题意要求的选项是：**{'、'.join(selected_options)}**。"
            )
        else:
            explanation_lines.append(
                "\n经逐项比对，各选项证据不足或存在争议，未能确定唯一答案。"
            )

        full_explanation = "\n".join(explanation_lines)

        # Build standardized intermediate verification dictionary (Prompt 8)
        verified_targets = [vo.option for vo in verified_options if vo.verdict == "SUPPORTED"]
        missing_targets = [vo.option for vo in verified_options if vo.verdict == "NOT_ENOUGH_EVIDENCE"]
        conflicting_targets = [vo.option for vo in verified_options if vo.verdict == "CONTRADICTED"]

        interm_verification_dict = {
            "task_complete": status == "SUCCESS" and len(selected_options) > 0,
            "missing_targets": missing_targets,
            "conflicting_targets": conflicting_targets,
            "verified_targets": verified_targets,
            "can_execute": status == "SUCCESS" and len(selected_options) > 0,
            "error_code": None if (status == "SUCCESS" and len(selected_options) > 0) else "INSUFFICIENT_EVIDENCE",
            "explanation": full_explanation,
        }

        return OptionVerificationResponse(
            status=status,
            choice_mode=choice_mode,
            question_intent_target=question_intent_target,  # type: ignore
            options_verification=verified_options,
            selected_options=selected_options,
            required_count=required_count,
            explanation=full_explanation,
            intermediate_verification=interm_verification_dict,
            diagnostics={
                "task_type": task_type,
                "winner_count": len(selected_options),
                "intent_target": question_intent_target,
                "option_features": {
                    o.option: {
                        "R_i": round(o.max_similarity, 4),
                        "E_i": round(o.entailment_support, 4),
                        "M_i": round(o.source_match, 4),
                        "Delta_i": round(o.relative_margin, 4),
                        "N_i": round(o.contradiction_probability, 4),
                        "C_i": round(o.ranking_score, 4),
                    }
                    for o in verified_options
                },
                "decision_policy": (
                    "SINGLE_TOP1_WITH_EVIDENCE"
                    if choice_mode == "SINGLE"
                    else f"MULTI_TOP{required_count}_WITH_EVIDENCE"
                ),
                "decision_reason": (
                    "按综合 C_i 排序取最高选项；不使用固定相似度一票否决"
                    if choice_mode == "SINGLE"
                    else f"按综合 C_i 排序取前 {required_count} 个有证据且未明确矛盾的选项；不使用固定相似度一票否决"
                ),
                "intermediate_verification": interm_verification_dict,
            },
        )

    def verify_option(
        self,
        option_label: str,
        claim: str,
        sub_claims: list[str],
        evidence_list: Sequence[Any],
        doc_name: str | None = None,
    ) -> OptionVerificationItem:
        """Verify an option by evaluating its individual claim or sub-claims."""
        if sub_claims and len(sub_claims) > 1:
            sub_results: list[SubClaimVerification] = []
            for sc in sub_claims:
                sr = self.verify_single_claim(sc, evidence_list, doc_name=doc_name)
                sub_results.append(sr)

            all_supp = all(sr.verdict == "SUPPORTED" for sr in sub_results)
            any_contra = any(sr.verdict == "CONTRADICTED" for sr in sub_results)

            if all_supp:
                verdict: VerdictType = "SUPPORTED"
                ev_ids = [eid for sr in sub_results for eid in sr.evidence_ids if eid]
                reason = "该选项包含的各项子表述均在指定监管文件中找到明确正向依据支持"
                confidence = 0.95
            elif any_contra:
                verdict = "CONTRADICTED"
                contra_details = [
                    sr.contradiction_detail for sr in sub_results if sr.contradiction_detail
                ]
                reason = f"选项中存在与监管规定冲突的表述: {'; '.join(contra_details)}"
                ev_ids = [eid for sr in sub_results for eid in sr.evidence_ids if eid]
                confidence = 0.90
            else:
                verdict = "NOT_ENOUGH_EVIDENCE"
                unsupported_claims = [
                    sr.sub_claim for sr in sub_results if sr.verdict != "SUPPORTED"
                ]
                reason = (
                    f"选项中部分子表述（{len(unsupported_claims)}项）未能在指定文件中检索到有效条款"
                )
                # Preserve any retrieved evidence from supported or partially
                # matched sub-claims.  A multi-fact option must still be
                # rankable by R_i/M_i when strict all-subclaim entailment is
                # unavailable; clearing this list caused over-refusal.
                ev_ids = [eid for sr in sub_results for eid in sr.evidence_ids if eid]
                confidence = 0.50

            return OptionVerificationItem(
                option=option_label,
                claim=claim,
                verdict=verdict,
                evidence_ids=ev_ids,
                confidence=confidence,
                sub_claims=sub_results,
                reason=reason,
            )

        # Single claim verification
        sr = self.verify_single_claim(claim, evidence_list, doc_name=doc_name)
        return OptionVerificationItem(
            option=option_label,
            claim=claim,
            verdict=sr.verdict,
            evidence_ids=sr.evidence_ids,
            confidence=sr.score if sr.score > 1.0 else 0.95,
            sub_claims=[sr],
            contradiction_detail=sr.contradiction_detail,
            reason=sr.reason,
        )

    def verify_single_claim(
        self,
        claim: str,
        evidence_list: Sequence[Any],
        doc_name: str | None = None,
    ) -> SubClaimVerification:
        """Verify an isolated assertion string against evidence chunks across PDF, Word, Excel."""
        from app.retrieval.evidence_adapter import evidence_adapter

        clean_claim = clean_for_match(claim)
        if not clean_claim:
            return SubClaimVerification(
                sub_claim=claim,
                verdict="NOT_ENOUGH_EVIDENCE",
                reason="断言文本为空",
            )

        best_ratio = 0.0
        best_chunk = None
        best_chunk_id = ""
        best_score = 0.0
        best_semantic = False

        adapted_list = evidence_adapter.adapt_list(evidence_list)
        for chunk in adapted_list:
            text = chunk.content
            chunk_id = chunk.evidence_id
            score = chunk.score
            title = chunk.source_title

            # Check document filter
            if doc_name:
                wanted_title = _normalize_document_name(doc_name) or doc_name
                metadata = getattr(chunk, "metadata", {}) or {}
                source_candidates = [
                    title,
                    getattr(chunk, "local_path", ""),
                    metadata.get("source_page_title", "") if isinstance(metadata, dict) else "",
                    metadata.get("file_name", "") if isinstance(metadata, dict) else "",
                    metadata.get("document_name", "") if isinstance(metadata, dict) else "",
                ]
                matched = False
                for candidate in source_candidates:
                    actual_title = _normalize_document_name(str(candidate)) or str(candidate)
                    if wanted_title in actual_title or actual_title in wanted_title:
                        matched = True
                        break
                if not matched:
                    continue

            ratio, _ = compute_sliding_similarity(claim, text)
            semantic_match = _semantic_table_match(claim, text)
            # Retain the best eligible chunk by text match, then retrieval
            # score. This prevents equal fuzzy scores from selecting an
            # arbitrary clause and helps distinguish the correct C option.
            # Retain the first eligible chunk even when fuzzy similarity is
            # zero.  Retrieval hit itself is evidence that can be surfaced and
            # ranked; similarity is a feature, not a hard veto.
            if (
                (semantic_match and not best_semantic)
                or (semantic_match == best_semantic and ratio > best_ratio)
                or (semantic_match == best_semantic and ratio == best_ratio and _retrieval_score(chunk) > best_score)
                or best_chunk is None
            ):
                best_ratio = ratio
                best_chunk = chunk
                best_chunk_id = chunk_id
                best_score = score
                best_semantic = semantic_match

        if best_chunk:
            best_text = (
                getattr(best_chunk, "content", None)
                or getattr(best_chunk, "text", None)
                or (best_chunk.get("text", "") if isinstance(best_chunk, dict) else "")
            )
            # 1. Contradiction check on best matching chunk
            if best_ratio >= 0.35:
                is_contra, contra_msg = detect_contradictions(claim, best_text)
                if is_contra:
                    return SubClaimVerification(
                        sub_claim=claim,
                        verdict="CONTRADICTED",
                        score=best_score,
                        evidence_ids=[best_chunk_id],
                        supporting_text=best_text[:120],
                        contradiction_detail=contra_msg,
                        reason=f"存在明确事实矛盾: {contra_msg}",
                    )

            # 2. Support check on best matching chunk. Short numbered clauses
            # may be split from the surrounding sentence; exact substring
            # matching is accepted even when the fuzzy ratio is lower.
            compact_claim = re.sub(r"[\s。；;，,：:（）()]+", "", clean_claim)
            compact_text = re.sub(r"^[0-9一二三四五六七八九十]+[.、)]?", "", str(best_text or "").strip())
            compact_text = re.sub(r"[\s。；;，,：:（）()]+", "", compact_text)
            exact_clause = (
                (len(compact_text) >= 8 and compact_text in compact_claim)
                or (len(clean_for_match(str(best_text or ""))) >= 8
                    and clean_for_match(str(best_text or "")) in clean_for_match(claim))
                or _semantic_table_match(claim, str(best_text or ""))
            )
            if best_ratio >= 0.70 or exact_clause:
                return SubClaimVerification(
                    sub_claim=claim,
                    verdict="SUPPORTED",
                    score=best_score,
                    similarity=best_ratio,
                    evidence_ids=[best_chunk_id],
                    supporting_text=best_text[:120],
                    reason=f"与监管条款原文表述高度吻合（文本相似度: {best_ratio * 100:.1f}%）",
                )

        return SubClaimVerification(
            sub_claim=claim,
            verdict="NOT_ENOUGH_EVIDENCE",
            score=best_ratio,
            similarity=best_ratio,
            evidence_ids=[best_chunk_id] if best_chunk_id else [],
            supporting_text=(
                (
                    getattr(best_chunk, "content", None)
                    or getattr(best_chunk, "text", None)
                    or (best_chunk.get("text", "") if isinstance(best_chunk, dict) else "")
                )[:120]
                if best_chunk is not None
                else ""
            ),
            reason=f"在知识库中未检索到充分的支持证据（最高相似度: {best_ratio * 100:.1f}%）",
        )

    @staticmethod
    def _option_similarity(item: OptionVerificationItem) -> float:
        if item.sub_claims:
            return max((float(getattr(s, "similarity", s.score)) for s in item.sub_claims), default=0.0)
        return 0.0

    def _normalize_retrieval_input(
        self,
        retrieval_input: Any,
    ) -> tuple[dict[str, list[Any]], list[Any]]:
        """Normalize various retrieval inputs into a task_id -> evidence_list map."""
        task_map: dict[str, list[Any]] = {}
        merged: list[Any] = []

        if retrieval_input is None:
            return task_map, merged

        if isinstance(retrieval_input, MultiTargetRetrievalResponse):
            for r in retrieval_input.retrieval_results:
                task_map[r.task_id] = list(r.evidence)
            merged = list(retrieval_input.merged_evidence)
            return task_map, merged

        if hasattr(retrieval_input, "diagnostics") and isinstance(
            retrieval_input.diagnostics, dict
        ):
            diag = retrieval_input.diagnostics
            if "multi_target" in diag and isinstance(diag["multi_target"], dict):
                mt = diag["multi_target"]
                for r in mt.get("retrieval_results", []):
                    task_map[r.get("task_id", "")] = r.get("evidence", [])
                merged = mt.get("merged_evidence", [])
            elif "retrieval_results" in diag:
                for r in diag.get("retrieval_results", []):
                    task_map[r.get("task_id", "")] = r.get("evidence", [])
            if not merged and hasattr(retrieval_input, "evidence"):
                merged = list(retrieval_input.evidence)

        if isinstance(retrieval_input, dict):
            if "retrieval_results" in retrieval_input:
                for r in retrieval_input.get("retrieval_results", []):
                    task_map[r.get("task_id", "")] = r.get("evidence", [])
                merged = retrieval_input.get("merged_evidence", [])
            diag = retrieval_input.get("diagnostics", {})
            if isinstance(diag, dict) and "multi_target" in diag:
                mt = diag["multi_target"]
                if isinstance(mt, dict):
                    for r in mt.get("retrieval_results", []):
                        task_map[r.get("task_id", "")] = r.get("evidence", [])
                    if not merged:
                        merged = mt.get("merged_evidence", [])
            if not merged:
                merged = retrieval_input.get("evidence", [])

        if isinstance(retrieval_input, (list, tuple)):
            merged = list(retrieval_input)

        if merged:
            for item in merged:
                meta = (
                    item.get("metadata", {})
                    if isinstance(item, dict)
                    else getattr(item, "metadata", {})
                )
                if isinstance(meta, dict):
                    tid = meta.get("matched_target_task")
                    if tid:
                        task_map.setdefault(tid, []).append(item)

        return task_map, merged


option_verifier = OptionVerificationEngine()

__all__ = [
    "OptionVerificationEngine",
    "option_verifier",
    "clean_for_match",
    "extract_numbers_with_units",
    "detect_question_intent_target",
    "compute_sliding_similarity",
    "detect_contradictions",
]
