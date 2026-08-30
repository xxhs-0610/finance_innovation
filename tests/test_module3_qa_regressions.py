"""Regression checks for QA findings from the Module 3 evaluation pass."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.retrieval.multi_target_retriever import (  # noqa: E402
    _narrow_table_dimension,
    find_matching_table_titles,
)
from app.schemas.chunk_schema import SearchResult, SourceInfo  # noqa: E402


class Module3QaRegressionTest(unittest.TestCase):
    DB_PATH = Path(__file__).resolve().parents[1] / "data/processed/kb_rebuild/metadata.db"

    def test_explicit_year_does_not_fall_back_to_wrong_year(self) -> None:
        titles = find_matching_table_titles(
            self.DB_PATH,
            "2023年商业银行主要指标分机构类情况表（季度）",
            "商业银行分机构类情况表",
        )
        self.assertTrue(any("2023" in title for title in titles))
        self.assertFalse(any("2021" in title for title in titles))

    def test_explicit_dimension_is_reduced_to_one_source_cell(self) -> None:
        metadata = {
            "metric_name": "不良贷款余额",
            "row_header": "一季度 / 不良贷款余额",
            "values": [
                {"cell_ref": "A5", "header": "机构", "value": "一季度"},
                {"cell_ref": "C5", "header": "大型商业银行", "value": "12461.058486995"},
                {"cell_ref": "D5", "header": "股份制商业银行", "value": "5234.461835107"},
            ],
        }
        result = _narrow_table_dimension(
            SearchResult(
                chunk_id="fixture",
                chunk_type="table",
                score=1.0,
                text="row",
                source=SourceInfo(doc_id="doc", title="table", cell_ref="A5:H5"),
                metadata=metadata,
            ),
            "大型商业银行",
        )
        self.assertEqual(result.source.cell_ref, "C5")
        self.assertEqual(result.metadata["cell_ref"], "C5")
        self.assertEqual(len(result.metadata["values"]), 1)
        self.assertEqual(result.metadata["table_cell_selection"]["status"], "exact_dimension_cell")


if __name__ == "__main__":
    unittest.main()
