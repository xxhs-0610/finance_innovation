"""Task Planner for RegTrust-RAG.

Translates DOMAIN_QA questions into structured, deterministic execution plans (TaskPlan).
Adheres strictly to the 6 core business task types:
  1. TABLE_LOOKUP: Single/multiple point table data extraction
  2. TABLE_COMPARE: Multi-candidate extremum comparison or ranking
  3. TABLE_CALCULATION: Multi-operand mathematical operations on table values
  4. FACT_SINGLE_CHOICE: Single-choice verification with text claims
  5. FACT_MULTI_CHOICE: Multi-choice verification with required correct count and sub-claims
  6. DIRECT_FACT_QA: Direct regulatory facts, thresholds, compliance, and procedure questions

Key Principles:
  - Preserves ALL candidate targets given by user without false pruning.
  - Recognizes multiple operands for calculation as operands, NOT ambiguous conflicts.
  - Never guesses or hallucinates unmentioned files, dates, or metrics.
  - Does NOT execute retrieval; strictly produces execution plans.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.task_plan_schema import (
    ChoiceOption,
    SourceConstraints,
    TableCandidate,
    TableOperand,
    TableSource,
    TableTarget,
    TaskPlan,
)
from app.utils.logger import get_logger

logger = get_logger("app.retrieval.task_planner")

DOCUMENT_RE = re.compile(r"《([^》]+)》")
CLAUSE_RE = re.compile(r"第[零〇一二三四五六七八九十百千万\d]+条")
PERIOD_RE = re.compile(
    r"(?:19|20)\d{2}(?:"
    r"年(?:0?[1-9]|1[0-2])月|"
    r"年(?:第?[一二三四1234]季度|上半年|下半年|年末|年度)?|"
    r"[Qq][1-4]|-(?:0[1-9]|1[0-2])"
    r")"
)
SCOPE_RE = re.compile(
    r"在[“\"‘']([^”\"’']+)口径下|[“\"‘']([^”\"’']+)口径|口径[：:]\s*([^\s，。？！?]+)"
)


def extract_choice_options(text: str) -> tuple[str, dict[str, str]]:
    """Extract question stem and choice options (A, B, C, D) from question text.

    Supports diverse delimiter formats: 'A:', 'A：', 'A.', 'A、', multiline or inline.
    """
    raw = (text or "").strip()
    pattern = re.compile(
        r"(?:^|[\n\s，。？！?；;])(?P<label>[A-D])\s*[:：\.、]\s*(?P<content>.*?)(?=(?:[\n\s，。？！?；;][A-D]\s*[:：\.、]|$))",
        re.DOTALL,
    )
    matches = list(pattern.finditer(raw))
    # In compact inline questions, punctuation before an option may be a
    # closing quote/parenthesis or a comma. Accept these separators while
    # still requiring at least two labelled choices.
    if len(matches) < 2:
        compact_pattern = re.compile(
            r"(?P<label>[A-D])\s*[:：\.、]\s*(?P<content>.*?)(?=(?:\s*[A-D]\s*[:：\.、]|$))",
            re.DOTALL,
        )
        matches = list(compact_pattern.finditer(raw))
    if len(matches) >= 2:
        labels = [m.group("label") for m in matches]
        if "A" in labels:
            first_match = matches[0]
            first_a_pos = raw.find(first_match.group("label"), first_match.start())
            stem = raw[:first_a_pos].rstrip(" \t\n,，:：?？。；;!")
            options: dict[str, str] = {}
            for m in matches:
                lbl = m.group("label")
                content = m.group("content").strip()
                content = content.replace("\\n", " ").strip()
                options[lbl] = content
            return stem, options
    return raw, {}


def extract_sheet_name(text: str) -> str | None:
    """Extract Excel sheet name from query text, properly handling nested parentheses."""
    # Example: （工作表：人身保险公司（月度） ） or （工作表：商业银行分机构类情况表）
    m = re.search(
        r"[（\(]工作表[：:]\s*(.*?)(?:[）\)]\s*(?:[）\)]|，|,|。|在|下|“|\"|'|口径|$))",
        text,
    )
    if m:
        sheet = m.group(1).strip()
        if sheet.count("（") > sheet.count("）"):
            sheet += "）"
        elif sheet.count("(") > sheet.count(")"):
            sheet += ")"
        return sheet
    m2 = re.search(r"工作表[：:]\s*([^\s，。？！?,]+)", text)
    if m2:
        return m2.group(1).rstrip("）)").strip()
    return None


class TaskPlanner:
    """Intelligent task execution planner for banking regulation QA."""

    def plan(
        self,
        question: str,
        task_type: str | Any | None = None,
        options: dict[str, str] | None = None,
        semantic_hint: dict[str, Any] | None = None,
    ) -> TaskPlan:
        """Analyze user query and decompose into an actionable TaskPlan."""
        raw = (question or "").strip()
        stem, extracted_opts = extract_choice_options(raw)
        effective_opts = options or extracted_opts

        # Normalize task_type if RouteDecision passed
        if hasattr(task_type, "task_type"):
            effective_task_type = getattr(task_type, "task_type", None) or getattr(task_type, "qa_type", None)
        else:
            effective_task_type = task_type

        norm_task_type = self._normalize_task_type(effective_task_type or self._detect_task_type(stem, effective_opts))

        # A question that names an Excel/report source and asks for one value is
        # a table lookup even when it is presented with A-D numeric answers.
        # Do not override an explicit comparison/calculation route: those
        # questions also contain numeric options and often ask "多少".
        # Previously this check ran twice and converted TABLE_CALCULATION (and
        # TABLE_COMPARE) into TABLE_LOOKUP, losing required operands/candidates.
        if (
            norm_task_type not in {"TABLE_COMPARE", "TABLE_CALCULATION"}
            and self._is_numeric_table_lookup(raw, effective_opts)
        ):
            norm_task_type = "TABLE_LOOKUP"

        # 2. Extract common entities (Strictly without hallucination)
        doc_match = DOCUMENT_RE.search(raw)
        file_name = doc_match.group(1).strip() if doc_match else None
        sheet_name = extract_sheet_name(raw)

        scope_match = SCOPE_RE.search(raw)
        scope: str | None = None
        if scope_match:
            scope = (
                scope_match.group(1) or scope_match.group(2) or scope_match.group(3) or ""
            ).strip()
        elif "口径" in raw:
            m = re.search(r"“([^”]+)”\s*口径", raw)
            if m:
                scope = m.group(1).strip()

        # 3. Dispatch to type-specific planner
        if norm_task_type == "TABLE_LOOKUP":
            plan = self._plan_table_lookup(stem, raw, file_name, sheet_name, scope, effective_opts)
        elif norm_task_type == "TABLE_COMPARE":
            plan = self._plan_table_compare(stem, raw, file_name, sheet_name, scope, effective_opts)
        elif norm_task_type == "TABLE_CALCULATION":
            plan = self._plan_table_calculation(stem, raw, file_name, sheet_name, scope, effective_opts)
        elif norm_task_type == "FACT_SINGLE_CHOICE":
            plan = self._plan_fact_single_choice(stem, raw, file_name, effective_opts)
        elif norm_task_type == "FACT_MULTI_CHOICE":
            plan = self._plan_fact_multi_choice(stem, raw, file_name, effective_opts)
        else:
            plan = self._plan_direct_fact_qa(stem, raw, file_name)

        # Apply DeepSeek's explicit entities only when the deterministic parser
        # did not already find them. This keeps the model as a semantic aid,
        # never as an authority that can invent source facts.
        if semantic_hint and isinstance(semantic_hint, dict):
            if plan.source and not plan.source.file_name and semantic_hint.get("document_name"):
                plan.source.file_name = str(semantic_hint["document_name"]).strip()
            if plan.source and not plan.source.sheet_name and semantic_hint.get("sheet_name"):
                plan.source.sheet_name = str(semantic_hint["sheet_name"]).strip()
            if not plan.scope and semantic_hint.get("scope"):
                plan.scope = str(semantic_hint["scope"]).strip()
            if plan.task_type == "TABLE_LOOKUP" and semantic_hint.get("indicator"):
                indicator = str(semantic_hint["indicator"]).strip()
                if plan.targets:
                    target = plan.targets[0]
                    if not target.indicator or target.indicator == (plan.source.file_name if plan.source else ""):
                        target.indicator = indicator
                    if not target.row or target.row == "合计":
                        target.row = indicator

        plan.question = raw
        logger.info(
            f"[TaskPlanner] 生成执行计划 | task_type={plan.task_type} | "
            f"source={plan.source.to_dict() if plan.source else (plan.source_constraints.to_dict() if plan.source_constraints else None)}"
        )
        return plan

    def _is_numeric_table_lookup(self, question: str, options: dict[str, str]) -> bool:
        if len(options) < 2:
            return False
        has_table_source = any(
            marker in question
            for marker in ("Excel", "工作表", "报表", "统计表", "情况表", "本年累计", "截至当期", "口径")
        )
        asks_for_value = any(marker in question for marker in ("是多少", "多少", "数值"))
        numeric_option_re = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*(?:%|亿元|万元|元|万件|件)?\s*$")
        return has_table_source and asks_for_value and all(
            numeric_option_re.fullmatch(str(value or "")) for value in options.values()
        )

    def _normalize_task_type(self, task_type: str) -> str:
        """Map legacy or alternative aliases to 6 core task types."""
        m = {
            "表格取数": "TABLE_LOOKUP",
            "TABLE_LOOKUP": "TABLE_LOOKUP",
            "table_lookup": "TABLE_LOOKUP",
            "表格比较": "TABLE_COMPARE",
            "TABLE_COMPARE": "TABLE_COMPARE",
            "table_compare": "TABLE_COMPARE",
            "表格计算": "TABLE_CALCULATION",
            "TABLE_CALCULATION": "TABLE_CALCULATION",
            "table_calc": "TABLE_CALCULATION",
            "单事实检索": "FACT_SINGLE_CHOICE",
            "FACT_SINGLE_CHOICE": "FACT_SINGLE_CHOICE",
            "single_choice": "FACT_SINGLE_CHOICE",
            "多事实检索": "FACT_MULTI_CHOICE",
            "FACT_MULTI_CHOICE": "FACT_MULTI_CHOICE",
            "multi_choice": "FACT_MULTI_CHOICE",
            "DIRECT_FACT_QA": "DIRECT_FACT_QA",
            "direct_fact_qa": "DIRECT_FACT_QA",
            "REGULATION_FACT": "DIRECT_FACT_QA",
            "THRESHOLD_RULE": "DIRECT_FACT_QA",
            "COMPLIANCE_JUDGMENT": "DIRECT_FACT_QA",
            "PROCEDURE_PROCESS": "DIRECT_FACT_QA",
            "DEFINITION_EXPLANATION": "DIRECT_FACT_QA",
        }
        return m.get(task_type, "DIRECT_FACT_QA")

    def _detect_task_type(self, stem: str, options: dict[str, str]) -> str:
        """Fallback task type detection if not routed."""
        text = stem
        if re.search(
            r"(?:两处取数|取数并计算|从.*?到.*?的数值变化|数值变化约为多少|数值变化是多少|数值变化为多少|数值变化|相差多少|相差约为多少|差距是多少|差额是多少)",
            text,
        ):
            return "TABLE_CALCULATION"
        if re.search(
            r"(?:哪一项数值最高|哪一项数值最低|哪项数值最高|哪项数值最低|哪一项最高|哪一项最低|哪项最高|哪项最低|数值最高|数值最低|哪一项最大|哪一项最小|谁最高|谁最低|谁最大|谁最小|比较.*?谁)",
            text,
        ):
            return "TABLE_COMPARE"
        if any(k in text for k in ("Excel", "统计表", "情况表", "工作表", "口径", "截至当期", "本年累计", "报表")) or PERIOD_RE.search(text):
            if any(w in text for w in ("是多少", "多少", "数值", "情况", "余额")):
                return "TABLE_LOOKUP"
        if re.search(
            r"(?:下列哪两项|下列哪几项|哪些表述正确|哪两项表述正确|两项表述均属于|均属于该材料内容|均正确|多项选择)",
            text,
        ) or (options and any("；" in v for v in options.values())):
            return "FACT_MULTI_CHOICE"
        if options or re.search(
            r"(?:下列哪项|下列哪一项|以下哪一项|与材料内容一致|下列选项中|下列说法|哪一项表述正确)",
            text,
        ):
            return "FACT_SINGLE_CHOICE"
        return "DIRECT_FACT_QA"

    def _plan_table_lookup(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
        sheet_name: str | None,
        scope: str | None,
        options: dict[str, str],
    ) -> TaskPlan:
        targets: list[TableTarget] = []
        quoted_targets = re.findall(r"“([^”]+)”|‘([^’]+)’", stem)
        target_names = [
            q[0] or q[1]
            for q in quoted_targets
            if (q[0] or q[1]) not in {scope, file_name, sheet_name}
        ]

        row_target = target_names[0] if target_names else None
        col_target = scope
        if scope and "/" in scope:
            col_target = scope.split("/")[0].strip()

        targets.append(
            TableTarget(
                row=row_target or "合计",
                column=col_target or "本年累计",
                indicator=row_target or file_name or "",
            )
        )

        is_incomplete = (
            row_target is None
            and file_name is None
            and not options
            and not any(
                w in stem
                for w in (
                    "全国合计", "合计", "总计", "收入", "支出", "余额", "比例", "率",
                    "资产", "负债", "资本", "存款", "贷款", "投资", "保费",
                )
            )
        )

        return TaskPlan(
            task_type="TABLE_LOOKUP",
            source=TableSource(file_name=file_name, sheet_name=sheet_name),
            scope=scope,
            targets=targets,
            options=options,
            need_clarification=is_incomplete,
        )

    def _plan_table_compare(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
        sheet_name: str | None,
        scope: str | None,
        options: dict[str, str],
    ) -> TaskPlan:
        op = "MAX"
        if any(w in stem for w in ("最低", "最小", "最少", "谁低", "谁少", "更低", "更小", "更少", "谁更低", "谁更小", "谁更少")):
            op = "MIN"
        elif any(w in stem for w in ("排序", "从大到小", "从小到大")):
            op = "SORT"

        candidates: list[TableCandidate] = []
        if options:
            for lbl, target in options.items():
                candidates.append(TableCandidate(label=lbl, target=target.strip()))
        else:
            quoted = re.findall(r"[“\"‘']([^”\"’']+)[”\"’']", stem)
            if quoted:
                for idx, q in enumerate(quoted):
                    if q != scope and q != file_name and q != sheet_name:
                        candidates.append(TableCandidate(label=chr(65 + idx), target=q))
            if not candidates:
                # Parse candidates from conjunctions: "A与B谁更...", "A、B、C按大小比较谁最大", "A和B哪项更高"
                clean_stem = stem
                if file_name and f"《{file_name}》" in clean_stem:
                    clean_stem = clean_stem.replace(f"《{file_name}》", "")
                if scope:
                    clean_stem = clean_stem.replace(scope, "")

                m = re.search(r"(?:在.*?中[，,])?\s*(?:在.*?口径下[，,])?\s*(?:比较)?(?P<cands>[^，,。?？]+?)(?:按大小比较|谁|哪个|哪项)", clean_stem)
                if m:
                    cand_str = m.group("cands").strip()
                    parts = re.split(r"[与和、及,，\s]+", cand_str)
                    clean_parts = [
                        p.strip() for p in parts
                        if p.strip() and p.strip() not in (scope, file_name, sheet_name, "比较", "中", "口径下", "按大小比较")
                    ]
                    for idx, cp in enumerate(clean_parts):
                        candidates.append(TableCandidate(label=chr(65 + idx), target=cp))

        return TaskPlan(
            task_type="TABLE_COMPARE",
            source=TableSource(file_name=file_name, sheet_name=sheet_name),
            operation=op,
            scope=scope,
            candidates=candidates,
            options=options,
            need_clarification=False,
        )

    def _plan_table_calculation(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
        sheet_name: str | None,
        scope: str | None,
        options: dict[str, str],
    ) -> TaskPlan:
        op = "SUBTRACT"
        if any(w in stem for w in ("两者之和", "求和", "总和", "合计为")):
            op = "SUM"
        elif any(w in stem for w in ("变化率", "增长率", "增幅", "降幅", "比率")):
            op = "RATIO"

        operands: list[TableOperand] = []
        expression = ""

        # Pattern 1: “全国合计”从“合计”到“健康险”的数值变化
        m1 = re.search(
            r"[“\"‘'](?P<row>[^”\"’']+)[”\"’']\s*从\s*[“\"‘'](?P<from_col>[^”\"’']+)[”\"’']\s*到\s*[“\"‘'](?P<to_col>[^”\"’']+)[”\"’']",
            stem,
        )
        # Pattern 2: 从“合计”到“健康险”的数值变化
        m2 = re.search(
            r"从\s*[“\"‘'](?P<from_col>[^”\"’']+)[”\"’']\s*到\s*[“\"‘'](?P<to_col>[^”\"’']+)[”\"’']",
            stem,
        )
        # Pattern 3: 合计与健康险相差多少
        m3 = re.search(
            r"[“\"‘']?(?P<op1>[^”\"’'\s]+)[”\"’']?\s*与\s*[“\"‘']?(?P<op2>[^”\"’'\s]+)[”\"’']?\s*(?:相差|差距|之和)",
            stem,
        )

        # Robust Unicode fallback for the common form:
        # “指标”从“起始口径”到“结束口径”。  The original patterns were
        # written against mojibake quote characters and can miss perfectly
        # normal Chinese input after a locale/encoding round-trip.
        if not (m1 or m2):
            m_unicode = re.search(
                r'[\u201c\"「『](?P<row>[^\u201d\"」』]+)[\u201d\"」』]\s*'
                r'从\s*[\u201c\"「『](?P<from_col>[^\u201d\"」』]+)[\u201d\"」』]\s*'
                r'到\s*[\u201c\"「『](?P<to_col>[^\u201d\"」』]+)[\u201d\"」』]',
                stem,
            )
            if m_unicode:
                m1 = m_unicode

        if not (m1 or m2):
            m_unicode2 = re.search(
                r'从\s*[\u201c\"「『](?P<from_col>[^\u201d\"」』]+)[\u201d\"」』]\s*'
                r'到\s*[\u201c\"「『](?P<to_col>[^\u201d\"」』]+)[\u201d\"」』]',
                stem,
            )
            if m_unicode2:
                m2 = m_unicode2

        if m1:
            row_name = m1.group("row").strip()
            from_col = m1.group("from_col").strip()
            to_col = m1.group("to_col").strip()
            operands = [
                TableOperand(name=from_col, row=row_name, column=from_col),
                TableOperand(name=to_col, row=row_name, column=to_col),
            ]
            expression = (
                f"{to_col} - {from_col}" if op == "SUBTRACT" else f"{from_col} + {to_col}"
            )
        elif m2:
            from_col = m2.group("from_col").strip()
            to_col = m2.group("to_col").strip()
            row_match = re.search(r"[“\"‘']([^”\"’']+)行?[”\"’']", stem[: m2.start()])
            row_name = row_match.group(1).strip() if row_match else None
            operands = [
                TableOperand(name=from_col, row=row_name, column=from_col),
                TableOperand(name=to_col, row=row_name, column=to_col),
            ]
            expression = (
                f"{to_col} - {from_col}" if op == "SUBTRACT" else f"{from_col} + {to_col}"
            )
        elif m3:
            op1 = m3.group("op1").strip()
            op2 = m3.group("op2").strip()
            operands = [
                TableOperand(name=op1, row=None, column=op1),
                TableOperand(name=op2, row=None, column=op2),
            ]
            expression = f"{op2} - {op1}" if op == "SUBTRACT" else f"{op1} + {op2}"
        else:
            operands = [
                TableOperand(name="操作数1", row=None, column=None),
                TableOperand(name="操作数2", row=None, column=None),
            ]
            expression = "操作数2 - 操作数1"

        return TaskPlan(
            task_type="TABLE_CALCULATION",
            source=TableSource(file_name=file_name, sheet_name=sheet_name),
            operation=op,
            expression=expression,
            operands=operands,
            options=options,
            need_clarification=False,
        )

    def _plan_fact_single_choice(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
        options: dict[str, str],
    ) -> TaskPlan:
        clause_match = CLAUSE_RE.search(raw)
        article_number = clause_match.group(0) if clause_match else None

        opts_list: list[ChoiceOption] = []
        for lbl, claim in options.items():
            opts_list.append(ChoiceOption(label=lbl, claim=claim.strip()))

        return TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            source_constraints=SourceConstraints(
                document_name=file_name,
                article_number=article_number,
            ),
            choice_mode="SINGLE",
            options=opts_list,
            need_clarification=False,
        )

    def _plan_fact_multi_choice(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
        options: dict[str, str],
    ) -> TaskPlan:
        # A question asking for “which option group contains two statements”
        # expects one answer label (the group), while ordinary multi-fact
        # questions may request multiple answer labels.
        count = 1 if ("哪一组" in stem or "哪一组选项" in stem) else 2
        if "三项" in stem or "三组" in stem:
            count = 3
        elif "四项" in stem:
            count = 4

        opts_list: list[ChoiceOption] = []
        for lbl, claim in options.items():
            sub_claims = [s.strip() for s in re.split(r"[；;]", claim) if s.strip()]
            opts_list.append(
                ChoiceOption(
                    label=lbl,
                    claim=claim.strip(),
                    sub_claims=sub_claims if len(sub_claims) > 1 else [],
                )
            )

        return TaskPlan(
            task_type="FACT_MULTI_CHOICE",
            source_constraints=SourceConstraints(document_name=file_name),
            choice_mode="MULTI",
            required_correct_count=count,
            options=opts_list,
            need_clarification=False,
        )

    def _plan_direct_fact_qa(
        self,
        stem: str,
        raw: str,
        file_name: str | None,
    ) -> TaskPlan:
        clause_match = CLAUSE_RE.search(raw)
        article_number = clause_match.group(0) if clause_match else None

        keywords = [w for w in (file_name, article_number) if w]
        if not keywords:
            keywords = [stem]

        return TaskPlan(
            task_type="DIRECT_FACT_QA",
            source_constraints=SourceConstraints(
                document_name=file_name,
                article_number=article_number,
            ),
            query_keywords=keywords,
            need_clarification=False,
        )


task_planner = TaskPlanner()

__all__ = [
    "TaskPlanner",
    "task_planner",
    "extract_choice_options",
    "extract_sheet_name",
]
