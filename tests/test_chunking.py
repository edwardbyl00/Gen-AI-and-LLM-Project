from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from scripts.chunking import (
    chunk_document,
    enrich_document_structure,
    semantic_header_rows,
    split_to_fit,
    token_count,
    validate_chunks,
)


class FakeTokenizer:
    is_fast = True

    def __call__(
        self,
        text: str,
        add_special_tokens: bool = True,
        truncation: bool = False,
        return_offsets_mapping: bool = False,
    ) -> dict:
        del truncation
        spans = [match.span() for match in re.finditer(r"\S+", text)]
        ids = list(range(len(spans) + (2 if add_special_tokens else 0)))
        result = {"input_ids": ids}
        if return_offsets_mapping:
            result["offset_mapping"] = spans
        return result


def document(blocks: list[dict], document_id: str = "T01") -> dict:
    return {
        "document_id": document_id,
        "source": "HDB",
        "title": "Housing eligibility",
        "document_type": "policy",
        "source_url": "https://example.gov.sg",
        "retrieved_at": "2026-10-17",
        "effective_date": None,
        "source_capture_status": "not_applicable",
        "blocks": blocks,
    }


class ChunkingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokenizer = FakeTokenizer()

    def test_count_includes_special_tokens(self) -> None:
        self.assertEqual(token_count("one two three", self.tokenizer), 5)

    def test_semantic_split_is_lossless_and_within_limit(self) -> None:
        text = "First sentence has several words. Second sentence has several words. Third sentence ends."
        pieces, forced = split_to_fit(text, "Document: Test", self.tokenizer, 10)
        self.assertGreater(len(pieces), 1)
        self.assertFalse(forced)
        self.assertEqual(" ".join(pieces), text)
        self.assertTrue(all(token_count(f"Document: Test\n\n{piece}", self.tokenizer) <= 10 for piece in pieces))

    def test_headings_are_context_not_standalone_chunks(self) -> None:
        doc = document([
            {"block_id": "b1", "type": "heading", "level": 1, "section_path": ["Citizenship"], "text": "Citizenship"},
            {"block_id": "b2", "type": "paragraph", "section_path": ["Citizenship"], "text": "At least one citizen is required."},
        ])
        chunks = chunk_document(doc, self.tokenizer, target=30, maximum=40)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Section: Citizenship", chunks[0]["content"])
        self.assertEqual(chunks[0]["source_block_ids"], ["b2"])

    def test_long_legal_unit_has_consistent_links(self) -> None:
        text = "2.—(1) " + "alpha " * 14 + "(2) " + "beta " * 14 + "(3) " + "gamma " * 14
        doc = document([{
            "block_id": "b1", "type": "legal_provision", "section_path": ["PART II"],
            "section_number": "2", "section_title": "Conditions", "text": text,
        }], "S01")
        chunks = chunk_document(doc, self.tokenizer, target=20, maximum=28)
        self.assertGreater(len(chunks), 1)
        self.assertIn("(1)", chunks[0]["source_content"])
        self.assertTrue(all(chunk["requires_context"] for chunk in chunks))
        self.assertEqual([chunk["part_index"] for chunk in chunks], list(range(1, len(chunks) + 1)))
        self.assertEqual(chunks[0]["next_chunk_id"], chunks[1]["chunk_id"])
        self.assertEqual(chunks[1]["previous_chunk_id"], chunks[0]["chunk_id"])

    def test_table_preserves_row_and_column_context(self) -> None:
        doc = document([{
            "block_id": "b1", "type": "table", "section_path": ["Income ceiling"],
            "table": {"row_count": 2, "column_count": 2, "cells": [
                {"row": 0, "column": 0, "rowspan": 1, "colspan": 1, "is_header": True, "text": "Household"},
                {"row": 0, "column": 1, "rowspan": 1, "colspan": 1, "is_header": True, "text": "Income"},
                {"row": 1, "column": 0, "rowspan": 1, "colspan": 1, "is_header": False, "text": "Family"},
                {"row": 1, "column": 1, "rowspan": 1, "colspan": 1, "is_header": False, "text": "$14,000"},
            ]},
        }])
        chunks = chunk_document(doc, self.tokenizer, target=40, maximum=50)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Table row: Family", chunks[0]["content"])
        self.assertIn("Income: $14,000", chunks[0]["content"])
        self.assertEqual(chunks[0]["table_fragments"][0]["row_label"], "Family")

    def test_explicit_flat_document_labels_populate_hierarchy(self) -> None:
        doc = document([
            {"block_id": "b1", "type": "paragraph", "section_path": [], "text": "PART A — Eligibility"},
            {"block_id": "b2", "type": "paragraph", "section_path": [], "text": "1. Age rules"},
            {"block_id": "b3", "type": "paragraph", "section_path": [], "text": "a. You must be aged 21."},
        ], "C02_A")
        chunks = chunk_document(doc, self.tokenizer, target=30, maximum=40)
        self.assertEqual(chunks[-1]["hierarchy"]["part_or_chapter"], "PART A")
        self.assertIn("a.", chunks[-1]["hierarchy"]["list_labels"])
        self.assertEqual(chunks[-1]["hierarchy"]["parent_clause"], "1")

    def test_validator_accepts_valid_chunks(self) -> None:
        doc = document([{"block_id": "b1", "type": "paragraph", "section_path": ["Age"], "text": "Applicants must be 21."}])
        chunks = chunk_document(doc, self.tokenizer, target=30, maximum=40)
        failures = [issue for issue in validate_chunks([doc], chunks, self.tokenizer, 40) if issue["severity"] == "FAIL"]
        self.assertEqual(failures, [])

    def test_explicit_first_row_labels_can_be_recovered_as_headers(self) -> None:
        matrix = [
            ["Type of property", "Maximum amount of CPF that can be used"],
            ["HDB flat", "Purchase price"],
        ]
        self.assertEqual(semantic_header_rows(matrix), [0])
        self.assertEqual(semantic_header_rows([["Purchase price", "$240,000"], ["Loan", "$200,000"]]), [])
        self.assertEqual(semantic_header_rows([
            ["Household Alpha retains savings", "Household Beta uses all savings"],
            ["$40,000\nRemaining balance", "$0\nRemaining balance"],
        ]), [0])

    def test_adjacent_comparison_table_inherits_verified_subject_headers(self) -> None:
        def table(block_id: str, rows: list[list[str]]) -> dict:
            return {
                "block_id": block_id, "type": "table", "section_path": ["Comparison"],
                "table": {
                    "row_count": len(rows), "column_count": len(rows[0]),
                    "cells": [
                        {"row": row, "column": col, "rowspan": 1, "colspan": 1,
                         "is_header": False, "text": value}
                        for row, values in enumerate(rows) for col, value in enumerate(values)
                    ],
                },
            }
        doc = document([
            table("b1", [
                ["Household Alpha retains savings", "Household Beta uses all savings"],
                ["$40,000\nRemaining balance", "$0\nRemaining balance"],
            ]),
            {"block_id": "b2", "type": "paragraph", "section_path": ["Comparison"],
             "text": "Their respective decisions produce these payments:"},
            table("b3", [
                ["Loan\n$470,000", "Loan\n$430,000"],
                ["Instalment\n$2,514", "Instalment\n$2,300"],
            ]),
        ])
        chunks = chunk_document(doc, self.tokenizer, target=80, maximum=100)
        second_table = [chunk for chunk in chunks if "b3" in chunk["source_block_ids"]]
        self.assertTrue(second_table)
        self.assertTrue(all("Household Alpha retains savings:" in chunk["content"] for chunk in second_table))
        self.assertTrue(all("Household Beta uses all savings:" in chunk["content"] for chunk in second_table))
        self.assertTrue(all("inherited_comparison_headers" in chunk["flags"] for chunk in second_table))

    def test_raw_cpf_heading_css_enriches_paths_without_editing_input(self) -> None:
        doc = document([
            {"block_id": "b1", "type": "paragraph", "section_path": [], "text": "Eligibility"},
            {"block_id": "b2", "type": "paragraph", "section_path": [], "text": "You must qualify."},
        ], "C01")
        doc["source"] = "CPF"
        doc["source_filename"] = "sample.html"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cpf").mkdir()
            (root / "cpf" / "sample.html").write_text(
                '<div class="title__text headline-3">Eligibility</div><p>You must qualify.</p>',
                encoding="utf-8",
            )
            enriched = enrich_document_structure(doc, root)
        self.assertEqual(enriched["blocks"][1]["section_path"], ["Eligibility"])
        self.assertEqual(doc["blocks"][1]["section_path"], [])


if __name__ == "__main__":
    unittest.main()
