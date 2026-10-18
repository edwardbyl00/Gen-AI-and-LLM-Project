from __future__ import annotations

import unittest

from scripts.chunking import (
    chunk_document,
    count_tokens,
    split_legal_text,
    table_units,
    window_text,
)


class ChunkingTests(unittest.TestCase):
    def test_regex_token_count_is_deterministic(self) -> None:
        self.assertEqual(count_tokens("CPF OA: $20,000 and 5%."), 5)

    def test_long_text_windows_overlap_without_truncating_end(self) -> None:
        text = " ".join(f"word{i}" for i in range(20))
        windows = window_text(text, 10, 2)
        self.assertEqual([count_tokens(value) for value, _ in windows], [10, 10, 4])
        self.assertEqual([overlap for _, overlap in windows], [0, 2, 2])
        self.assertTrue(windows[-1][0].endswith("word19"))

    def test_table_is_split_by_rows_and_repeats_header(self) -> None:
        block = {
            "block_id": "b0001",
            "type": "table",
            "section_path": ["Limits"],
            "table": {
                "row_count": 3,
                "column_count": 2,
                "cells": [
                    {"row": 0, "column": 0, "rowspan": 1, "colspan": 1, "is_header": True, "text": "Type"},
                    {"row": 0, "column": 1, "rowspan": 1, "colspan": 1, "is_header": True, "text": "Limit"},
                    {"row": 1, "column": 0, "rowspan": 1, "colspan": 1, "is_header": False, "text": "Family one two three"},
                    {"row": 1, "column": 1, "rowspan": 1, "colspan": 1, "is_header": False, "text": "$80,000"},
                    {"row": 2, "column": 0, "rowspan": 1, "colspan": 1, "is_header": False, "text": "Single four five six"},
                    {"row": 2, "column": 1, "rowspan": 1, "colspan": 1, "is_header": False, "text": "$40,000"},
                ],
            },
        }
        units = table_units(block, chunk_size=8)
        self.assertEqual(len(units), 2)
        self.assertTrue(all("Type" in unit.content and "Limit" in unit.content for unit in units))
        self.assertIn("table_header_repeated", units[1].flags)
        self.assertEqual(units[0].table_fragment["source_block_id"], "b0001")
        self.assertEqual(units[0].table_fragment["original_row_indices"], [1])
        self.assertEqual(units[1].table_fragment["original_row_indices"], [2])

    def test_long_legal_section_splits_at_numeric_subsections(self) -> None:
        text = "2.—(1) First rule alpha beta gamma. (2) Second rule delta epsilon. (3) Third rule zeta eta."
        pieces = split_legal_text(text, chunk_size=10, overlap=2)
        self.assertGreaterEqual(len(pieces), 3)
        self.assertTrue(pieces[0][0].startswith("2.—(1)"))
        self.assertTrue(any(piece.startswith("(2)") for piece, _, _ in pieces))

    def test_chunks_preserve_traceability_and_section_boundaries(self) -> None:
        document = {
            "document_id": "H01",
            "source": "HDB",
            "title": "Eligibility",
            "document_type": "policy",
            "source_url": "https://example.gov.sg",
            "retrieved_at": "2026-10-17",
            "effective_date": None,
            "source_capture_status": "not_applicable",
            "blocks": [
                {"block_id": "b0001", "type": "heading", "level": 2, "section_path": ["Citizenship"], "text": "Citizenship"},
                {"block_id": "b0002", "type": "paragraph", "section_path": ["Citizenship"], "text": "At least one citizen is required."},
                {"block_id": "b0003", "type": "heading", "level": 2, "section_path": ["Age"], "text": "Age"},
                {"block_id": "b0004", "type": "paragraph", "section_path": ["Age"], "text": "Applicants must meet the age rule."},
            ],
        }
        chunks = chunk_document(document, chunk_size=50, overlap=5)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section_path"], ["Citizenship"])
        self.assertEqual(chunks[1]["section_path"], ["Age"])
        self.assertEqual(chunks[0]["source_block_ids"], ["b0001", "b0002"])
        self.assertEqual(chunks[1]["source_block_ids"], ["b0003", "b0004"])
        self.assertTrue(all(chunk["source_url"] for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
