from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.indexing.build_kb import build_kb
from app.indexing.index_reader import KnowledgeBaseReader
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.hybrid_retriever import (
    HybridRetriever,
    reciprocal_rank_fusion,
    retrieve_evidence,
)
from app.retrieval.query_parser import parse_query
from app.retrieval.metadata_filter import build_filter_attempts
from app.retrieval.evidence_selector import select_evidence
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.reranker import PairwiseReranker, RuleBasedReranker
from app.retrieval.table_evidence import narrow_table_evidence
from app.retrieval.table_retriever import TableRetriever
from app.retrieval.vector_retriever import KnowledgeBaseVectorBackend, VectorRetriever
from app.schemas.chunk_schema import SearchResult, SourceInfo


class QueryParserTest(unittest.TestCase):
    def test_parse_threshold_query(self) -> None:
        analysis = parse_query("商业银行核心一级资本充足率最低要求是多少？")

        self.assertEqual(analysis.query_type, "clause_threshold")
        self.assertEqual(analysis.preferred_chunk_type, "clause")
        self.assertEqual(analysis.entities["institution"], "商业银行")
        self.assertEqual(analysis.entities["metric"], "核心一级资本充足率")

    def test_parse_bank_tier(self) -> None:
        analysis = parse_query("第三档商业银行核心一级资本充足率最低要求是多少？")

        self.assertEqual(analysis.entities["bank_tier"], "第三档商业银行")
        self.assertIn("第三档商业银行", analysis.keywords)

    def test_procedure_word_at_least_is_not_threshold(self) -> None:
        analysis = parse_query("恢复措施至少从哪些方面分析？")

        self.assertEqual(analysis.query_type, "business_procedure")
        self.assertNotIn("metric", analysis.entities)

    def test_parse_table_query(self) -> None:
        analysis = parse_query("2025年三季度商业银行资本充足率是多少？")

        self.assertEqual(analysis.query_type, "table_lookup")
        self.assertEqual(analysis.preferred_chunk_type, "table")
        self.assertEqual(analysis.entities["period"], "2025年三季度")
        self.assertEqual(analysis.entities["normalized_period"], "2025Q3")
        self.assertEqual(analysis.filters["publish_date"], "2025")

    def test_parse_monthly_table_query(self) -> None:
        analysis = parse_query("2025年9月商业银行资产总额是多少？")

        self.assertEqual(analysis.query_type, "table_lookup")
        self.assertEqual(analysis.entities["metric"], "资产总额")
        self.assertEqual(analysis.entities["normalized_period"], "2025-09")

    def test_year_metric_value_query_is_table_lookup(self) -> None:
        analysis = parse_query("2025年商业银行资本充足率是多少？")

        self.assertEqual(analysis.query_type, "table_lookup")
        self.assertEqual(analysis.entities["period"], "2025年")

    def test_year_metric_fragment_is_table_lookup(self) -> None:
        analysis = parse_query("2025年商业银行主要监管指标一级资本充足率")

        self.assertEqual(analysis.query_type, "table_lookup")
        self.assertEqual(analysis.entities["metric"], "一级资本充足率")

    def test_parse_document_number_range_operator_and_value(self) -> None:
        analysis = parse_query(
            "根据银保监发〔2022〕15号，2022年至2024年该指标不得低于8%。"
        )

        self.assertEqual(analysis.entities["document_number"], "银保监发〔2022〕15号")
        self.assertEqual(analysis.entities["start_year"], "2022")
        self.assertEqual(analysis.entities["end_year"], "2024")
        self.assertEqual(analysis.entities["operator"], "not_less_than")
        self.assertEqual(analysis.entities["value"], "8%")
        self.assertNotIn("period", analysis.entities)
        self.assertNotIn("publish_date", analysis.filters)


class MetadataFilterTest(unittest.TestCase):
    def test_only_publish_date_is_relaxed(self) -> None:
        attempts = build_filter_attempts(
            {
                "title": "商业银行资本管理办法",
                "issuer": "国家金融监督管理总局",
                "publish_date": "2024",
            }
        )

        self.assertEqual([item.name for item in attempts], ["strict", "relaxed_publish_date"])
        self.assertEqual(
            attempts[1].filters,
            {
                "title": "商业银行资本管理办法",
                "issuer": "国家金融监督管理总局",
            },
        )
        self.assertEqual(attempts[1].relaxed_filters, ("publish_date",))


class EntityFilterTest(unittest.TestCase):
    def test_clause_number_is_a_strict_post_filter(self) -> None:
        source_two = SourceInfo(doc_id="doc001", clause_no="第二条")
        source_ten = SourceInfo(doc_id="doc001", clause_no="第十条")
        candidates = [
            SearchResult("two", "clause", 0.9, "第二条内容", source_two),
            SearchResult("ten", "clause", 0.8, "第十条内容", source_ten),
        ]

        results = apply_entity_filters(
            parse_query("《商业银行资本管理办法》第十条是什么？"),
            candidates,
        )

        self.assertEqual([item.chunk_id for item in results], ["ten"])
        self.assertEqual(
            results[0].metadata["entity_filtering"]["checked_fields"]["clause_no"],
            "第十条",
        )

    def test_table_year_range_uses_period_before_publish_date(self) -> None:
        source = SourceInfo(doc_id="doc101", publish_date="2025-09-30")
        candidates = [
            SearchResult(
                "inside",
                "table",
                0.9,
                "2023年指标",
                source,
                metadata={"metric_name": "资本充足率", "period": "2023Q4"},
            ),
            SearchResult(
                "outside",
                "table",
                0.8,
                "2025年指标",
                source,
                metadata={"metric_name": "资本充足率", "period": "2025Q3"},
            ),
        ]

        results = apply_entity_filters(
            parse_query("2022年至2024年资本充足率变化如何？"),
            candidates,
        )

        self.assertEqual([item.chunk_id for item in results], ["inside"])
        self.assertEqual(
            results[0].metadata["entity_filtering"]["checked_fields"][
                "candidate_year"
            ],
            2023,
        )

    def test_table_quarter_strictly_excludes_other_years(self) -> None:
        def row(chunk_id: str, year: str) -> SearchResult:
            return SearchResult(
                chunk_id,
                "table",
                0.9,
                f"{year}年商业银行指标",
                SourceInfo(doc_id=chunk_id, title=f"{year}年监管指标"),
                metadata={
                    "metric_name": "资本充足率",
                    "period": year,
                    "values": [
                        {"header": "三季度", "value": "0.15", "cell_ref": "D44"}
                    ],
                },
            )

        results = apply_entity_filters(
            parse_query("2025年三季度商业银行资本充足率是多少？"),
            [row("2025", "2025"), row("2024", "2024")],
        )

        self.assertEqual([item.chunk_id for item in results], ["2025"])
        self.assertEqual(
            results[0].metadata["entity_filtering"]["checked_fields"][
                "requested_period"
            ],
            "2025Q3",
        )

    def test_table_metric_is_a_strict_filter(self) -> None:
        source = SourceInfo(doc_id="doc101", title="2025年监管指标")
        candidates = [
            SearchResult(
                "capital",
                "table",
                0.9,
                "资本充足率",
                source,
                metadata={"metric_name": "资本充足率", "period": "2025"},
            ),
            SearchResult(
                "tier-one",
                "table",
                0.8,
                "一级资本充足率",
                source,
                metadata={"metric_name": "一级资本充足率", "period": "2025"},
            ),
        ]

        results = apply_entity_filters(
            parse_query("2025年商业银行资本充足率是多少？"), candidates
        )

        self.assertEqual([item.chunk_id for item in results], ["capital"])

    def test_table_title_can_define_metric_for_region_row(self) -> None:
        candidate = SearchResult(
            "insurance",
            "table",
            0.9,
            "全国 | 合计=52145.77",
            SourceInfo(
                doc_id="insurance",
                title="2025年9月全国各地区原保险保费收入情况表",
                table_name="原保险保费收入情况表",
            ),
            metadata={"metric_name": "全国", "period": "2025-09"},
        )

        results = apply_entity_filters(
            parse_query("2025年9月原保险保费收入是多少？"), [candidate]
        )

        self.assertEqual([item.chunk_id for item in results], ["insurance"])

    def test_explicit_threshold_tier_requires_proven_tier_scope(self) -> None:
        unscoped = SearchResult(
            "unscoped",
            "clause",
            0.9,
            "核心一级资本充足率不得低于5%。",
            SourceInfo(doc_id="unscoped", title="资本监管规定"),
        )
        third_tier = SearchResult(
            "third-tier",
            "clause",
            0.8,
            "第三档商业银行核心一级资本充足率不得低于7.5%。",
            SourceInfo(doc_id="third-tier", title="第三档商业银行资本监管规定"),
        )

        results = apply_entity_filters(
            parse_query("第一档商业银行核心一级资本充足率最低要求是多少？"),
            [unscoped, third_tier],
        )

        self.assertEqual(results, [])

    def test_explicit_threshold_tier_keeps_matching_scope(self) -> None:
        third_tier = SearchResult(
            "third-tier",
            "clause",
            0.9,
            "第三档商业银行核心一级资本充足率不得低于7.5%。",
            SourceInfo(doc_id="third-tier", title="第三档商业银行资本监管规定"),
        )

        results = apply_entity_filters(
            parse_query("第三档商业银行核心一级资本充足率最低要求是多少？"),
            [third_tier],
        )

        self.assertEqual([item.chunk_id for item in results], ["third-tier"])


class ReciprocalRankFusionTest(unittest.TestCase):
    def test_result_in_multiple_retrievers_ranks_first(self) -> None:
        source = SourceInfo(doc_id="doc001")
        shared = SearchResult(
            "shared",
            "clause",
            10.0,
            "共同结果",
            source,
            metadata={"table_matching": {"matched_fields": ["metric_exact"]}},
        )
        keyword_only = SearchResult("keyword", "clause", 9.0, "关键词结果", source)
        vector_only = SearchResult("vector", "clause", 0.8, "向量结果", source)

        fused = reciprocal_rank_fusion(
            {
                "bm25": [keyword_only, shared],
                "vector": [shared, vector_only],
            }
        )

        self.assertEqual(fused[0].chunk_id, "shared")
        self.assertEqual(
            set(fused[0].metadata["retrieval"]["sources"]), {"bm25", "vector"}
        )
        self.assertEqual(
            fused[0].metadata["table_matching"]["matched_fields"],
            ["metric_exact"],
        )


class FakeVectorBackend:
    def __init__(self, result: SearchResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def search(self, query, *, top_k, chunk_type, filters):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "chunk_type": chunk_type,
                "filters": filters,
            }
        )
        if filters.get("publish_date") == "2024":
            return []
        return [self.result]


class VectorRetrieverTest(unittest.TestCase):
    def test_vector_backend_uses_same_visible_date_fallback(self) -> None:
        result = SearchResult(
            "doc001_clause_0001",
            "clause",
            0.88,
            "资本充足率规定",
            SourceInfo(
                doc_id="doc001",
                title="商业银行资本管理办法",
                source_url="https://example.com/doc001",
                clause_no="第十条",
            ),
        )
        backend = FakeVectorBackend(result)
        retriever = VectorRetriever(backend)
        analysis = parse_query("2024年《商业银行资本管理办法》第十条是什么？")

        results = retriever.search(analysis, top_k=5)

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(
            backend.calls[1]["filters"], {"title": "商业银行资本管理办法"}
        )
        self.assertEqual(
            results[0].metadata["filtering"]["attempt"],
            "relaxed_publish_date",
        )

    def test_module2_vector_adapter_disables_module2_reranking(self) -> None:
        class FakeReader:
            def __init__(self):
                self.kwargs = None

            def vector_search(self, query, **kwargs):
                self.kwargs = kwargs
                return []

        reader = FakeReader()
        backend = KnowledgeBaseVectorBackend(reader)

        backend.search(
            "资本充足率",
            top_k=20,
            chunk_type="clause",
            filters={"issuer": "国家金融监督管理总局"},
        )

        self.assertFalse(reader.kwargs["rerank"])
        self.assertEqual(reader.kwargs["chunk_type"], "clause")
        self.assertEqual(
            reader.kwargs["filters"], {"issuer": "国家金融监督管理总局"}
        )


class RerankerTest(unittest.TestCase):
    def test_pairwise_reranker_changes_order_and_keeps_previous_score(self) -> None:
        source = SourceInfo(doc_id="doc001")
        first = SearchResult("first", "clause", 0.03, "一般规定", source)
        second = SearchResult("second", "clause", 0.02, "最低要求为5%", source)
        reranker = PairwiseReranker(
            lambda pairs: [1.0 if "5%" in text else 0.1 for _, text in pairs],
            name="test-reranker",
        )

        results = reranker.rerank(
            parse_query("最低要求是多少？"), [first, second], top_k=2
        )

        self.assertEqual(results[0].chunk_id, "second")
        self.assertEqual(results[0].metadata["reranking"]["reranker"], "test-reranker")
        self.assertEqual(results[0].metadata["reranking"]["previous_score"], 0.02)

    def test_rule_reranker_penalizes_unrequested_narrow_bank_tier(self) -> None:
        generic = SearchResult(
            "generic",
            "clause",
            0.02,
            "核心一级资本充足率不得低于5%。",
            SourceInfo(doc_id="generic", title="商业银行资本管理办法"),
        )
        third_tier = SearchResult(
            "third-tier",
            "clause",
            0.03,
            "核心一级资本充足率不得低于7.5%。",
            SourceInfo(
                doc_id="third-tier",
                title="第三档商业银行资本监管规定",
            ),
        )

        results = RuleBasedReranker().rerank(
            parse_query("商业银行核心一级资本充足率最低要求是多少？"),
            [third_tier, generic],
            top_k=2,
        )

        self.assertEqual(results[0].chunk_id, "generic")
        self.assertIn(
            "narrower_bank_tier_than_query",
            results[1].metadata["reranking"]["reasons"],
        )


class FixedRetriever:
    name = "fixed"

    def __init__(self, results):
        self.results = results

    def search(self, analysis, top_k=20):
        return self.results[:top_k]


class FailingRetriever:
    name = "failing-vector"

    def search(self, analysis, top_k=20):
        raise RuntimeError("backend unavailable")


class HybridFailureIsolationTest(unittest.TestCase):
    def test_failed_vector_backend_keeps_other_evidence(self) -> None:
        source = SourceInfo(
            doc_id="doc001",
            title="商业银行资本管理办法",
            source_url="https://example.com/doc001",
            clause_no="第十条",
        )
        candidate = SearchResult(
            "doc001_clause_0001", "clause", 1.0, "资本充足率规定", source
        )
        retriever = HybridRetriever(
            [FixedRetriever([candidate]), FailingRetriever()]
        )

        response = retriever.search("资本充足率规定是什么？", top_k=1)

        self.assertEqual(len(response.evidence), 1)
        self.assertEqual(
            response.diagnostics["retrievers"]["failing-vector"]["status"],
            "failed",
        )
        self.assertEqual(response.diagnostics["failures"][0]["error_type"], "RuntimeError")

    def test_failed_reranker_keeps_rrf_order(self) -> None:
        source = SourceInfo(
            doc_id="doc001",
            title="商业银行资本管理办法",
            source_url="https://example.com/doc001",
            clause_no="第十条",
        )
        candidates = [
            SearchResult("first", "clause", 1.0, "第一条证据", source),
            SearchResult("second", "clause", 0.9, "第二条证据", source),
        ]
        reranker = PairwiseReranker(
            lambda pairs: (_ for _ in ()).throw(RuntimeError("model unavailable")),
            name="failing-reranker",
        )
        retriever = HybridRetriever(
            [FixedRetriever(candidates)], reranker=reranker
        )

        response = retriever.search("资本充足率规定是什么？", top_k=2)

        self.assertEqual(
            [item.chunk_id for item in response.evidence], ["first", "second"]
        )
        self.assertEqual(response.diagnostics["reranker"]["status"], "failed")
        self.assertEqual(response.diagnostics["failures"][0]["stage"], "reranking")


class EvidenceSelectorTest(unittest.TestCase):
    def test_missing_table_provenance_is_reported(self) -> None:
        candidate = SearchResult(
            "table-1",
            "table",
            0.9,
            "数值：12.35",
            SourceInfo(doc_id="doc101", title="监管统计表"),
            metadata={"value": "12.35"},
        )

        selected = select_evidence([candidate], top_k=1)

        quality = selected[0].metadata["evidence_quality"]
        self.assertFalse(quality["complete"])
        self.assertIn("source.cell_ref", quality["missing_fields"])
        self.assertIn("metadata.metric_name", quality["missing_fields"])

    def test_module1_table_row_values_are_complete_evidence(self) -> None:
        candidate = SearchResult(
            "table-row-1",
            "table",
            0.9,
            "全国 | 合计=52145.77 | 单位：亿元",
            SourceInfo(
                doc_id="doc101",
                title="全国保费收入情况表",
                source_url="https://example.com/doc101",
                table_name="全国保费收入情况表",
                cell_ref="B4:G4",
            ),
            metadata={
                "metric_name": "全国",
                "period": "2025-09",
                "values": [
                    {"header": "合计", "value": "52145.77", "cell_ref": "C4"}
                ],
            },
        )

        selected = select_evidence([candidate], top_k=1)

        self.assertTrue(selected[0].metadata["evidence_quality"]["complete"])

    def test_exact_table_cell_is_minimum_sufficient_evidence(self) -> None:
        source = SourceInfo(
            doc_id="doc101",
            title="监管统计指标",
            source_url="https://example.com/doc101",
            table_name="主要监管指标",
            cell_ref="B4",
        )
        exact = SearchResult(
            "table-exact",
            "table",
            0.9,
            "资本充足率为12.35%",
            source,
            metadata={
                "metric_name": "资本充足率",
                "period": "2025Q3",
                "value": "12.35",
                "table_matching": {
                    "matched_fields": ["metric_exact", "period_exact"]
                },
            },
        )
        other = SearchResult(
            "table-other", "table", 0.8, "其他指标", source, metadata={}
        )

        selected = select_evidence(
            [exact, other],
            top_k=5,
            analysis=parse_query("2025年三季度资本充足率是多少？"),
        )

        self.assertEqual([item.chunk_id for item in selected], ["table-exact"])

    def test_row_evidence_is_narrowed_to_requested_quarter_cell(self) -> None:
        candidate = SearchResult(
            "table-row",
            "table",
            0.9,
            "资本充足率，一季度至四季度",
            SourceInfo(
                doc_id="doc101",
                title="2025年商业银行主要监管指标情况表",
                table_name="商业银行主要监管指标",
                cell_ref="A44:E44",
            ),
            metadata={
                "metric_name": "资本充足率",
                "period": "2025",
                "unit": "%",
                "values": [
                    {"header": "一季度", "value": "0.15282", "cell_ref": "B44"},
                    {"header": "三季度", "value": "0.15359", "cell_ref": "D44"},
                ],
            },
        )

        narrowed = narrow_table_evidence(
            candidate, parse_query("2025年三季度资本充足率是多少？")
        )

        self.assertEqual(narrowed.source.cell_ref, "D44")
        self.assertEqual(narrowed.metadata["period"], "2025Q3")
        self.assertEqual(narrowed.metadata["value"], "0.15359")
        self.assertEqual(
            narrowed.metadata["table_cell_selection"]["original_cell_ref"],
            "A44:E44",
        )

    def test_row_label_cell_is_ignored_when_one_numeric_value_exists(self) -> None:
        candidate = SearchResult(
            "monthly-row",
            "table",
            0.9,
            "原保险保费收入，本年累计52145.77亿元",
            SourceInfo(
                doc_id="insurance",
                title="2025年9月保险业经营情况表",
                table_name="保险业经营情况表",
                cell_ref="B7:C7",
            ),
            metadata={
                "metric_name": "原保险保费收入",
                "row_header": "原保险保费收入",
                "period": "2025-09",
                "values": [
                    {
                        "header": "数值",
                        "value": "原保险保费收入",
                        "cell_ref": "B7",
                        "period": "2025-09",
                    },
                    {
                        "header": "本年累计 / 截至当期",
                        "value": "52145.77",
                        "value_numeric": "52145.770000000000000000",
                        "cell_ref": "C7",
                        "period": "2025-09",
                    },
                ],
            },
        )

        narrowed = narrow_table_evidence(
            candidate, parse_query("2025年9月原保险保费收入是多少？")
        )

        self.assertEqual(narrowed.source.cell_ref, "C7")
        self.assertEqual(narrowed.metadata["value"], "52145.77")
        self.assertEqual(
            narrowed.metadata["table_cell_selection"]["status"],
            "exact_period_cell",
        )

    def test_multiple_numeric_columns_are_marked_ambiguous(self) -> None:
        candidate = SearchResult(
            "monthly-wide-row",
            "table",
            0.9,
            "原保险保费收入，财产险与人身险",
            SourceInfo(
                doc_id="insurance",
                title="2025年9月保险业经营情况表",
                table_name="保险业经营情况表",
                cell_ref="C7:D7",
            ),
            metadata={
                "metric_name": "原保险保费收入",
                "period": "2025-09",
                "values": [
                    {
                        "header": "财产险",
                        "value": "100",
                        "value_numeric": "100",
                        "cell_ref": "C7",
                        "period": "2025-09",
                    },
                    {
                        "header": "人身险",
                        "value": "200",
                        "value_numeric": "200",
                        "cell_ref": "D7",
                        "period": "2025-09",
                    },
                ],
            },
        )

        narrowed = narrow_table_evidence(
            candidate, parse_query("2025年9月原保险保费收入是多少？")
        )

        selection = narrowed.metadata["table_cell_selection"]
        self.assertEqual(selection["status"], "ambiguous_dimension")
        self.assertEqual(selection["candidate_value_count"], 2)
        self.assertEqual(
            [item["label"] for item in selection["dimension_options"]],
            ["财产险", "人身险"],
        )

    def test_cross_document_query_prioritizes_document_diversity(self) -> None:
        source_one = SourceInfo(doc_id="doc001")
        source_two = SourceInfo(doc_id="doc002")
        candidates = [
            SearchResult("doc1-a", "clause", 0.9, "证据一", source_one),
            SearchResult("doc1-b", "clause", 0.8, "证据二", source_one),
            SearchResult("doc2-a", "clause", 0.7, "证据三", source_two),
        ]

        selected = select_evidence(
            candidates,
            top_k=2,
            analysis=parse_query("对比两个文件的资本管理规定"),
        )

        self.assertEqual([item.chunk_id for item in selected], ["doc1-a", "doc2-a"])


class TableRetrieverTest(unittest.TestCase):
    def test_exact_metric_and_period_rank_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=root / "indexes",
            )
            retriever = TableRetriever(
                KnowledgeBaseReader(processed_dir / "metadata.db")
            )

            results = retriever.search(
                parse_query("2025年三季度商业银行资本充足率是多少？"),
                top_k=3,
            )

            self.assertEqual(results[0].metadata["metric_name"], "资本充足率")
            self.assertEqual(
                results[0].metadata["table_matching"]["matched_fields"],
                ["metric_exact", "period_exact"],
            )


class RoutedTableRetriever:
    name = "routed-table"
    supported_query_types = frozenset({"table_lookup"})

    def __init__(self):
        self.call_count = 0

    def search(self, analysis, top_k=20):
        self.call_count += 1
        return []


class QueryRoutingTest(unittest.TestCase):
    def test_clause_query_skips_table_only_retriever(self) -> None:
        table_retriever = RoutedTableRetriever()
        retriever = HybridRetriever([table_retriever])

        response = retriever.search("资本充足率最低要求是多少？", top_k=3)

        self.assertEqual(table_retriever.call_count, 0)
        self.assertEqual(
            response.diagnostics["retrievers"]["routed-table"]["status"],
            "skipped",
        )

    def test_ambiguous_query_skips_all_retrievers(self) -> None:
        table_retriever = RoutedTableRetriever()
        retriever = HybridRetriever([table_retriever])

        response = retriever.search("怎么办？", top_k=3)

        self.assertEqual(response.analysis.query_type, "ambiguous")
        self.assertEqual(response.evidence, [])
        self.assertEqual(table_retriever.call_count, 0)
        self.assertEqual(response.diagnostics["reranker"]["status"], "skipped")
        self.assertEqual(response.status, "needs_clarification")
        self.assertFalse(response.module4_guidance["may_generate_answer"])

    def test_unsupported_query_is_refused_without_retrieval(self) -> None:
        retriever = RoutedTableRetriever()
        response = HybridRetriever([retriever]).search("今天北京天气怎么样？")

        self.assertEqual(response.analysis.query_type, "unsupported")
        self.assertEqual(response.status, "no_evidence")
        self.assertEqual(response.module4_guidance["action"], "refuse")
        self.assertEqual(retriever.call_count, 0)

    def test_missing_metric_requests_clarification_before_retrieval(self) -> None:
        retriever = RoutedTableRetriever()
        response = HybridRetriever([retriever]).search("2025年三季度是多少？")

        self.assertEqual(response.status, "needs_clarification")
        self.assertEqual(response.module4_guidance["missing_entities"], ["metric"])
        self.assertEqual(retriever.call_count, 0)


class Module3IntegrationTest(unittest.TestCase):
    def test_retrieve_clause_evidence_from_sample_kb(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=root / "indexes",
            )
            retriever = HybridRetriever(
                [BM25Retriever(KnowledgeBaseReader(processed_dir / "metadata.db"))]
            )

            response = retriever.search(
                "商业银行核心一级资本充足率最低要求是多少？", top_k=3
            )

            self.assertEqual(response.analysis.query_type, "clause_threshold")
            self.assertTrue(response.evidence)
            self.assertTrue(
                any("不得低于5%" in item.text for item in response.evidence)
            )
            self.assertTrue(
                all(item.chunk_type == "clause" for item in response.evidence)
            )

    def test_module4_compatibility_returns_evidence_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=root / "indexes",
            )

            evidence = retrieve_evidence(
                "2025年三季度商业银行资本充足率是多少？",
                top_k=1,
                db_path=processed_dir / "metadata.db",
            )

            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["chunk_type"], "table")
            self.assertIn("source", evidence[0])

    def test_module4_compatibility_hides_non_answerable_evidence(self) -> None:
        evidence = retrieve_evidence(
            "商业银行核心一级资本充足率最低要求是多少？",
            top_k=1,
        )

        self.assertEqual(evidence, [])

    def test_publish_date_fallback_is_visible_and_keeps_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=root / "indexes",
            )
            retriever = HybridRetriever(
                [BM25Retriever(KnowledgeBaseReader(processed_dir / "metadata.db"))]
            )

            response = retriever.search(
                "2024年《商业银行资本管理办法》第十条规定是什么？", top_k=1
            )

            self.assertEqual(len(response.evidence), 1)
            filtering = response.evidence[0].metadata["filtering"]
            self.assertEqual(filtering["attempt"], "relaxed_publish_date")
            self.assertEqual(filtering["relaxed_filters"], ["publish_date"])
            self.assertEqual(
                filtering["applied_filters"]["title"], "商业银行资本管理办法"
            )

    def test_real_table_pipeline_fuses_channels_and_returns_one_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed_dir = root / "processed"
            build_kb(
                "data/samples/parsed_docs.jsonl",
                "data/samples/parsed_tables.jsonl",
                processed_dir=processed_dir,
                indexes_dir=root / "indexes",
            )
            reader = KnowledgeBaseReader(processed_dir / "metadata.db")
            retriever = HybridRetriever(
                [BM25Retriever(reader), TableRetriever(reader)]
            )

            response = retriever.search(
                "2025年三季度商业银行资本充足率是多少？", top_k=5
            )

            self.assertEqual(len(response.evidence), 1)
            self.assertEqual(response.evidence[0].metadata["value"], "12.35")
            self.assertEqual(
                set(response.evidence[0].metadata["retrieval"]["sources"]),
                {"bm25", "table"},
            )
            self.assertIn("table_matching", response.evidence[0].metadata)

    def test_module4_receives_no_evidence_status(self) -> None:
        response = HybridRetriever([FixedRetriever([])]).search(
            "2035年三季度商业银行资本充足率是多少？",
            top_k=5,
        )

        self.assertEqual(response.status, "no_evidence")
        self.assertEqual(response.module4_guidance["action"], "refuse")
        self.assertFalse(response.module4_guidance["may_generate_answer"])

    def test_incomplete_provenance_is_not_answerable(self) -> None:
        result = SearchResult(
            "incomplete",
            "table",
            1.0,
            "资本充足率=0.15",
            SourceInfo(doc_id="doc101", title="监管指标"),
            metadata={
                "metric_name": "资本充足率",
                "period": "2025Q3",
                "value": "0.15",
                "table_matching": {
                    "matched_fields": ["metric_exact", "period_exact"]
                },
            },
        )
        response = HybridRetriever([FixedRetriever([result])]).search(
            "2025年三季度商业银行资本充足率是多少？",
            top_k=1,
        )

        self.assertEqual(response.status, "no_evidence")
        self.assertFalse(response.module4_guidance["may_generate_answer"])

    def test_unspecified_bank_tier_requests_clarification(self) -> None:
        result = SearchResult(
            "third-tier",
            "clause",
            1.0,
            "核心一级资本充足率不得低于7.5%。",
            SourceInfo(
                doc_id="third-tier",
                title="第三档商业银行资本监管规定",
                local_path="third-tier.docx",
                section_path=["第三档商业银行资本监管规定"],
            ),
        )
        response = HybridRetriever([FixedRetriever([result])]).search(
            "商业银行核心一级资本充足率最低要求是多少？",
            top_k=1,
        )

        self.assertEqual(response.status, "needs_clarification")
        self.assertEqual(
            response.module4_guidance["missing_entities"], ["bank_tier"]
        )

    def test_realistic_conditional_threshold_is_not_generic_minimum(self) -> None:
        conditional = SearchResult(
            "conditional",
            "clause",
            0.03,
            "核心一级资本充足率不低于14%的商业银行，可划分为A+级。",
            SourceInfo(
                doc_id="conditional",
                title="信用风险权重法风险暴露分类标准",
                local_path="conditional.docx",
                section_path=["金融机构风险暴露"],
            ),
        )
        tiered = SearchResult(
            "tiered",
            "clause",
            0.02,
            "第三档商业银行核心一级资本充足率不得低于7.5%。",
            SourceInfo(
                doc_id="tiered",
                title="第三档商业银行资本监管规定",
                local_path="tiered.docx",
                section_path=["第三档商业银行资本监管规定"],
            ),
        )
        response = HybridRetriever(
            [FixedRetriever([conditional, tiered])],
            reranker=RuleBasedReranker(),
        ).search("商业银行核心一级资本充足率最低要求是多少？", top_k=1)

        self.assertEqual(response.evidence[0].chunk_id, "tiered")
        self.assertEqual(response.status, "needs_clarification")

    def test_explicit_bank_tier_is_answerable(self) -> None:
        result = SearchResult(
            "third-tier",
            "clause",
            1.0,
            "核心一级资本充足率不得低于7.5%。",
            SourceInfo(
                doc_id="third-tier",
                title="第三档商业银行资本监管规定",
                local_path="third-tier.docx",
                section_path=["第三档商业银行资本监管规定"],
            ),
        )
        response = HybridRetriever([FixedRetriever([result])]).search(
            "第三档商业银行核心一级资本充足率最低要求是多少？",
            top_k=1,
        )

        self.assertEqual(response.status, "answerable")
        self.assertEqual(response.module4_guidance["action"], "answer")

    def test_ambiguous_table_dimension_is_handed_to_module4_as_clarification(self) -> None:
        result = SearchResult(
            "wide-table",
            "table",
            1.0,
            "原保险保费收入，财产险100亿元，人身险200亿元",
            SourceInfo(
                doc_id="insurance",
                title="2025年9月保险业经营情况表",
                local_path="insurance.xlsx",
                table_name="保险业经营情况表",
                cell_ref="C7:D7",
            ),
            metadata={
                "metric_name": "原保险保费收入",
                "period": "2025-09",
                "values": [
                    {
                        "header": "财产险",
                        "value": "100",
                        "value_numeric": "100",
                        "cell_ref": "C7",
                        "period": "2025-09",
                    },
                    {
                        "header": "人身险",
                        "value": "200",
                        "value_numeric": "200",
                        "cell_ref": "D7",
                        "period": "2025-09",
                    },
                ],
                "table_matching": {
                    "matched_fields": ["metric_exact", "period_exact"]
                },
            },
        )

        response = HybridRetriever([FixedRetriever([result])]).search(
            "2025年9月原保险保费收入是多少？", top_k=1
        )

        self.assertEqual(response.status, "needs_clarification")
        self.assertFalse(response.module4_guidance["may_generate_answer"])
        self.assertEqual(
            response.module4_guidance["missing_entities"], ["table_dimension"]
        )
        self.assertEqual(
            response.module4_guidance["clarification_options"],
            ["财产险", "人身险"],
        )

    def test_explicit_tier_with_unscoped_evidence_is_not_answerable(self) -> None:
        unscoped = SearchResult(
            "unscoped",
            "clause",
            1.0,
            "核心一级资本充足率不得低于5%。",
            SourceInfo(
                doc_id="unscoped",
                title="资本监管规定",
                local_path="capital.docx",
                section_path=["资本充足率要求"],
            ),
        )

        response = HybridRetriever([FixedRetriever([unscoped])]).search(
            "第一档商业银行核心一级资本充足率最低要求是多少？", top_k=1
        )

        self.assertEqual(response.status, "no_evidence")
        self.assertEqual(response.evidence, [])
        self.assertFalse(response.module4_guidance["may_generate_answer"])



if __name__ == "__main__":
    unittest.main()
