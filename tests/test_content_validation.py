from __future__ import annotations

import unittest

from scripts.content_validation import Question, best_evidence, source_ids


class ContentValidationTests(unittest.TestCase):
    def test_source_ids_resolve_named_and_numbered_files(self) -> None:
        self.assertEqual(
            source_ids(
                "Couples and Families (date).html; H05_C.html; "
                "C02-A_CPF_Housing_Scheme_Terms_Conditions.html.html"
            ),
            ["H01", "H05_C", "C02_A"],
        )

    def test_duplicate_source_is_mapped_to_canonical_document(self) -> None:
        self.assertEqual(source_ids("H09_C.html"), ["H05_B"])

    def test_comma_separated_source_ids_are_all_retained(self) -> None:
        self.assertEqual(source_ids("C04, C07, C02-B Multi-document"), ["C04", "C07", "C02_B"])

    def test_later_letter_suffix_is_retained(self) -> None:
        self.assertEqual(source_ids("H09_G.html"), ["H09_G"])

    def test_best_evidence_selects_relevant_block(self) -> None:
        question = Question(
            "CPF_30Q",
            "Q01",
            "Can CPF OA savings pay monthly housing loan instalments?",
            "Reference mapping only",
            ["C01"],
        )
        documents = {
            "C01": {
                "blocks": [
                    {"block_id": "b0001", "text": "General introduction."},
                    {
                        "block_id": "b0002",
                        "text": "CPF OA savings may pay monthly housing loan instalments.",
                    },
                ]
            }
        }
        block, document_id, block_id, score = best_evidence(question, documents)
        self.assertIsNotNone(block)
        self.assertEqual((document_id, block_id), ("C01", "b0002"))
        self.assertGreater(score, 0)


if __name__ == "__main__":
    unittest.main()
