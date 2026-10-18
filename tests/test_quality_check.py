from __future__ import annotations

import unittest

from scripts.quality_check import (
    evaluate_quality,
    excluded_exact_duplicate_ids,
    merge_overlapping_tokens,
    navigation_markers,
    sequence_covered,
    table_matrix,
    tokens,
)


class QualityCheckTests(unittest.TestCase):
    def test_sequence_coverage_ignores_table_line_break_markup(self) -> None:
        source = "Applicants must be citizens\nunless an exception applies"
        chunk = "Applicants must be citizens<br>unless an exception applies"
        self.assertTrue(sequence_covered(source, [chunk]))

    def test_sequence_coverage_detects_missing_condition(self) -> None:
        source = "Applicants must be citizens unless an exception applies"
        self.assertFalse(sequence_covered(source, ["Applicants must be citizens"]))

    def test_navigation_noise_detection(self) -> None:
        self.assertEqual(navigation_markers("Was this page helpful?"), ["feedback_widget"])
        self.assertEqual(navigation_markers("Applicants must meet the age rule."), [])

    def test_table_matrix_expands_merged_cells(self) -> None:
        table = {
            "row_count": 2,
            "column_count": 2,
            "cells": [
                {"row": 0, "column": 0, "rowspan": 1, "colspan": 2, "text": "Header"},
                {"row": 1, "column": 0, "rowspan": 1, "colspan": 1, "text": "Age"},
                {"row": 1, "column": 1, "rowspan": 1, "colspan": 1, "text": "21"},
            ],
        }
        self.assertEqual(table_matrix(table), [["Header", "Header"], ["Age", "21"]])

    def test_overlap_reconstruction_is_lossless(self) -> None:
        first = tokens("one two three four")
        second = tokens("three four five six")
        self.assertEqual(merge_overlapping_tokens(first, second), tokens("one two three four five six"))

    def test_exact_duplicate_exclusion_uses_report_action(self) -> None:
        rows = [{
            "document_id": "H09_C",
            "duplicate_type": "exact_normalized_content",
            "recommended_action": "exclude H09_C; retain canonical H05_B",
        }]
        self.assertEqual(excluded_exact_duplicate_ids(rows), ["H09_C"])

    def test_minimal_dataset_passes_traceability_and_numeric_checks(self) -> None:
        document = {
            "document_id": "H01",
            "source": "HDB",
            "title": "Eligibility",
            "source_url": "https://example.gov.sg",
            "retrieved_at": "2026-10-17",
            "raw_sha256": "hash",
            "content_sha256": "content-hash",
            "content": "Applicants must be at least 21 years old.",
            "blocks": [{"block_id": "b0001", "type": "paragraph", "section_path": ["Age"], "text": "Applicants must be at least 21 years old."}],
        }
        chunk = {
            "chunk_id": "H01_c0001",
            "document_id": "H01",
            "source": "HDB",
            "source_url": "https://example.gov.sg",
            "source_block_ids": ["b0001"],
            "section_path": ["Age"],
            "block_types": ["paragraph"],
            "flags": [],
            "content": "Applicants must be at least 21 years old.",
            "token_count": 8,
            "oversized": False,
        }
        inventory = [{"file_id": "H01", "parsing_status": "success", "content_extraction_status": "success"}]
        rows, metrics = evaluate_quality([document], [chunk], inventory, reparse_raw=False)
        by_id = {row.check_id: row for row in rows}
        self.assertEqual(by_id["G13"].status, "PASS")
        self.assertEqual(by_id["G14"].status, "PASS")
        self.assertEqual(by_id["G11"].status, "PASS")
        self.assertEqual(metrics["total_generated_chunks"], 1)


if __name__ == "__main__":
    unittest.main()
