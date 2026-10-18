from __future__ import annotations

import unittest

from scripts.deduplication import (
    detect_duplicates,
    normalized_content_hash,
    normalized_tokens,
    similarity,
    token_shingles,
)


def document(identifier: str, source: str, title: str, content: str) -> dict[str, str]:
    return {"document_id": identifier, "source": source, "title": title, "content": content}


class DeduplicationTests(unittest.TestCase):
    def test_normalized_hash_ignores_markdown_link_destination(self) -> None:
        first = "Read [policy](https://example.gov/a) conditions."
        second = "Read [policy](https://example.gov/b) conditions."
        self.assertEqual(normalized_content_hash(first), normalized_content_hash(second))

    def test_shingle_similarity_detects_contained_copy(self) -> None:
        short = normalized_tokens("alpha beta gamma delta epsilon zeta")
        long = normalized_tokens("intro words alpha beta gamma delta epsilon zeta ending words")
        jaccard, containment = similarity(token_shingles(short, 3), token_shingles(long, 3))
        self.assertLess(jaccard, 1.0)
        self.assertEqual(containment, 1.0)

    def test_inventory_exact_duplicate_is_excluded(self) -> None:
        docs = [document("H05_B", "HDB", "EIP", "same policy content")]
        inventory = [
            {
                "file_id": "H09_C",
                "source_organization": "HDB",
                "downstream_action": "exclude_exact_duplicate",
                "duplicate_of": "H05_B",
            }
        ]
        rows, excluded = detect_duplicates(docs, inventory)
        self.assertEqual(excluded, {"H09_C"})
        self.assertEqual(rows[0].duplicate_type, "exact_normalized_content")
        self.assertEqual(rows[0].recommended_action, "exclude H09_C; retain canonical H05_B")

    def test_near_duplicates_are_reported_but_retained(self) -> None:
        shared = "alpha beta gamma delta epsilon " * 10
        docs = [
            document("A", "HDB", "Families", shared + "family condition"),
            document("B", "HDB", "Singles", shared + "single condition"),
        ]
        rows, excluded = detect_duplicates(docs, [])
        near = [row for row in rows if row.duplicate_type == "near_duplicate"]
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0].recommended_action, "retain both")
        self.assertFalse(excluded)

    def test_cross_source_overlap_is_never_auto_excluded(self) -> None:
        content = (
            "CPF savings ordinary account remaining lease valuation price age 95 housing loan "
        ) * 8
        docs = [
            document("H", "HDB", "Financing", content),
            document("C", "CPF", "CPF usage", content + " agency guidance"),
        ]
        rows, excluded = detect_duplicates(docs, [])
        overlap = [row for row in rows if row.duplicate_type == "cross_source_topic_overlap"]
        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0].recommended_action, "retain both")
        self.assertFalse(excluded)


if __name__ == "__main__":
    unittest.main()
