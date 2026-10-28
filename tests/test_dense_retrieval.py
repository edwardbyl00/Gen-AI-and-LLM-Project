from __future__ import annotations

import unittest

import numpy as np

from scripts.evaluate_dense_retrieval import (
    FAILURE_FIELDS,
    RESULT_FIELDS,
    aggregate_metrics,
    question_metrics,
    top_k_indices,
    validate_ground_truth,
    validate_link_references,
    validate_output_schemas,
    validate_questions,
)


def questions():
    return [
        {
            "question_id": f"Q{i:02d}",
            "question": f"Unique question {i}?",
            "category": "Test",
            "test_type": "single",
            "candidate_sources_NOT_ground_truth": "hint",
            "source_verification_status": "candidate_only",
        }
        for i in range(1, 41)
    ]


def truth_row(qid="Q01", status="FULL", chunks="T_c0001", verified="true"):
    return {
        "question_id": qid,
        "question": f"Unique question {int(qid[1:])}?",
        "category": "Test",
        "coverage_status": status,
        "relevant_document_ids": "T" if chunks else "",
        "relevant_chunk_ids": chunks,
        "supporting_evidence": "Evidence",
        "required_conditions": "Conditions",
        "requires_multiple_chunks": "false",
        "requires_multiple_documents": "false",
        "requires_user_information": "false",
        "ground_truth_verified": verified,
        "relevance_label_scope": "verified_core_evidence",
        "review_notes": "",
    }


class DenseRetrievalTests(unittest.TestCase):
    def test_question_count_and_uniqueness(self):
        self.assertEqual(validate_questions(questions())["count"], 40)

    def test_question_duplicate_and_empty_are_rejected(self):
        rows = questions()
        rows[1]["question"] = rows[0]["question"]
        with self.assertRaises(ValueError):
            validate_questions(rows)
        rows = questions()
        rows[0]["question"] = ""
        with self.assertRaises(ValueError):
            validate_questions(rows)

    def test_cosine_similarity_for_normalized_vectors(self):
        docs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        query = np.array([1.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(docs @ query, np.array([1.0, 0.0]))

    def test_top_k_ranking_is_descending_and_stable(self):
        scores = np.array([0.1, 0.9, 0.9, 0.2])
        self.assertEqual(top_k_indices(scores, 3).tolist(), [1, 2, 3])

    def test_metric_calculation(self):
        metric = question_metrics({"a", "c"}, ["x", "a", "b", "c"])
        self.assertTrue(metric["hit_at_5"])
        self.assertEqual(metric["recall_at_5"], 1.0)
        self.assertEqual(metric["reciprocal_rank_at_10"], 0.5)

    def test_no_relevant_chunk_is_handled(self):
        metric = question_metrics(set(), ["x"])
        self.assertIsNone(metric["recall_at_5"])
        self.assertFalse(metric["hit_at_10"])

    def test_unverified_and_not_covered_are_excluded(self):
        qs = questions()[:3]
        gt = [
            truth_row("Q01"),
            truth_row("Q02", "UNVERIFIED", "T_c0001", "false"),
            truth_row("Q03", "NOT_COVERED", "", "true"),
        ]
        ranked = {"Q01": ["T_c0001"], "Q02": ["T_c0001"], "Q03": ["x"]}
        result = aggregate_metrics(qs, gt, ranked)
        self.assertEqual(result["aggregate"]["questions"], 1)
        self.assertIn("Q02", result["excluded_questions"])
        self.assertIn("Q03", result["excluded_questions"])

    def test_ground_truth_requires_existing_chunks_and_matching_documents(self):
        qs = questions()
        gt = [truth_row(row["question_id"]) for row in qs]
        chunks = [{"chunk_id": "T_c0001", "document_id": "T"}]
        self.assertEqual(validate_ground_truth(qs, gt, chunks)["verified"], 40)
        gt[0]["relevant_chunk_ids"] = "missing"
        with self.assertRaises(ValueError):
            validate_ground_truth(qs, gt, chunks)

    def test_ground_truth_preserves_original_question(self):
        qs = questions()
        gt = [truth_row(row["question_id"]) for row in qs]
        gt[0]["question"] = "rewritten"
        with self.assertRaises(ValueError):
            validate_ground_truth(qs, gt, [{"chunk_id": "T_c0001", "document_id": "T"}])

    def test_linked_chunk_reference_integrity(self):
        chunks = [
            {"chunk_id": "a", "previous_chunk_id": None, "next_chunk_id": "b"},
            {"chunk_id": "b", "previous_chunk_id": "a", "next_chunk_id": None},
        ]
        self.assertTrue(validate_link_references(chunks))
        chunks[1]["previous_chunk_id"] = "missing"
        self.assertFalse(validate_link_references(chunks))

    def test_output_schema_consistency(self):
        results = []
        for rank in range(1, 11):
            row = {field: "" for field in RESULT_FIELDS}
            row.update({"question_id": "Q01", "rank": rank})
            results.append(row)
        failure = {field: "" for field in FAILURE_FIELDS}
        self.assertTrue(validate_output_schemas(results, [failure], 1))
        results[0].pop("source")
        self.assertFalse(validate_output_schemas(results, [failure], 1))


if __name__ == "__main__":
    unittest.main()
