#!/usr/bin/env python3
"""Validate ground truth and run a pure BGE dense-retrieval baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer


MODEL_NAME = "BAAI/bge-base-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
LINK_FIELDS = (
    "parent_id", "part_index", "total_parts", "previous_chunk_id",
    "next_chunk_id", "requires_context",
)
QUESTION_FIELDS = (
    "question_id", "question", "category", "test_type",
    "candidate_sources_NOT_ground_truth", "source_verification_status",
)
GROUND_TRUTH_FIELDS = (
    "question_id", "question", "category", "coverage_status",
    "relevant_document_ids", "relevant_chunk_ids", "supporting_evidence",
    "required_conditions", "requires_multiple_chunks",
    "requires_multiple_documents", "requires_user_information",
    "ground_truth_verified", "relevance_label_scope", "review_notes",
)
RESULT_FIELDS = (
    "question_id", "question", "category", "rank", "chunk_id",
    "document_id", "source", "similarity_score", "chunk_text_excerpt",
    "is_relevant", "ground_truth_status",
)
FAILURE_FIELDS = (
    "question_id", "coverage_status", "first_relevant_rank", "hit_at_5",
    "hit_at_10", "likely_cause", "retrieval_evidence",
    "top_1_excerpt", "verified_ground_truth_evidence",
    "recommended_next_step", "notes",
)
FAILURE_GUIDANCE = {
    "H06": ("G;H", "Multiple conditional property-ownership rules are expressed as table cells rather than the question's yes/no wording.", "Hybrid retrieval or query decomposition"),
    "H09": ("F;G", "The question asks for a comparison spanning several independent eligibility rows.", "Query decomposition"),
    "H14": ("F;H", "Age, household route and flat type are distributed across HDB and CPF guidance.", "Query decomposition and linked evidence assembly"),
    "H15": ("F;G", "Three grant schemes and their conditions are distributed across separate documents.", "Query decomposition or multi-document retrieval"),
    "H22": ("E;F;G", "A broad comparison needs matching terms from two loan documents; generic finance chunks outrank the core comparison rows.", "Query decomposition followed by reranking"),
    "H25": ("E;F;H", "The query says HDB resale flat while the authoritative evidence is in separate generic BSD and ABSD documents.", "Hybrid retrieval or query decomposition, then reranking"),
    "H30": ("F;G;H", "The personalized multi-domain question combines eligibility, CPF, financing and tax conditions.", "Query decomposition and multi-document retrieval"),
    "C06": ("E;G", "Coverage requirements and exemption conditions live in different HPS chunks.", "Query decomposition or reranking"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def as_bool(value: Any) -> bool:
    return value is True or str(value).strip().casefold() == "true"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_questions(rows: list[dict[str, str]]) -> dict[str, Any]:
    if len(rows) != 40:
        raise ValueError(f"expected 40 questions, found {len(rows)}")
    missing_columns = sorted(set(QUESTION_FIELDS) - set(rows[0]))
    if missing_columns:
        raise ValueError(f"question CSV is missing columns: {missing_columns}")
    ids = [row["question_id"].strip() for row in rows]
    questions = [row["question"].strip() for row in rows]
    if any(not item for item in ids) or any(not item for item in questions):
        raise ValueError("question IDs and question text must not be empty")
    if len(set(ids)) != len(ids):
        raise ValueError("question IDs are not unique")
    normalized = [" ".join(question.casefold().split()) for question in questions]
    if len(set(normalized)) != len(normalized):
        raise ValueError("question text contains duplicates")
    return {"count": len(rows), "unique_ids": True, "no_empty_questions": True, "unique_questions": True}


def validate_ground_truth(
    questions: list[dict[str, str]],
    ground_truth: list[dict[str, str]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(ground_truth) != len(questions):
        raise ValueError("ground-truth row count does not match question count")
    missing_columns = sorted(set(GROUND_TRUTH_FIELDS) - set(ground_truth[0]))
    if missing_columns:
        raise ValueError(f"ground truth is missing columns: {missing_columns}")
    question_by_id = {row["question_id"]: row for row in questions}
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    if set(question_by_id) != {row["question_id"] for row in ground_truth}:
        raise ValueError("ground-truth question IDs do not match evaluation questions")
    for row in ground_truth:
        source = question_by_id[row["question_id"]]
        if row["question"] != source["question"] or row["category"] != source["category"]:
            raise ValueError(f"ground truth rewrites question/category for {row['question_id']}")
        status = row["coverage_status"]
        if status not in {"FULL", "PARTIAL", "NOT_COVERED", "UNVERIFIED"}:
            raise ValueError(f"invalid coverage status for {row['question_id']}: {status}")
        ids = parse_ids(row["relevant_chunk_ids"])
        if status in {"FULL", "PARTIAL"} and not ids:
            raise ValueError(f"covered question has no relevant chunks: {row['question_id']}")
        if status == "NOT_COVERED" and ids:
            raise ValueError(f"NOT_COVERED question has relevant chunks: {row['question_id']}")
        missing = [chunk_id for chunk_id in ids if chunk_id not in chunk_by_id]
        if missing:
            raise ValueError(f"unknown ground-truth chunks for {row['question_id']}: {missing}")
        actual_docs = {chunk_by_id[chunk_id]["document_id"] for chunk_id in ids}
        declared_docs = set(parse_ids(row["relevant_document_ids"]))
        if actual_docs != declared_docs:
            raise ValueError(
                f"document/chunk mismatch for {row['question_id']}: "
                f"declared={sorted(declared_docs)} actual={sorted(actual_docs)}"
            )
    counts = Counter(row["coverage_status"] for row in ground_truth)
    return {
        "count": len(ground_truth),
        "verified": sum(as_bool(row["ground_truth_verified"]) for row in ground_truth),
        "coverage": dict(sorted(counts.items())),
    }


def validate_embeddings(
    chunks_path: Path,
    chunks: list[dict[str, Any]],
    embeddings: np.ndarray,
    metadata: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, bool]:
    link_integrity = validate_link_references(chunks)
    checks = {
        "shape_1282_768": embeddings.shape == (1282, 768),
        "unique_chunk_ids": len(metadata) == 1282 and len({item["chunk_id"] for item in metadata}) == 1282,
        "ordering_matches_metadata": len(chunks) == len(metadata) and all(
            chunk["chunk_id"] == item["chunk_id"] and item.get("embedding_index") == index
            for index, (chunk, item) in enumerate(zip(chunks, metadata))
        ),
        "metadata_maps_to_chunks": len(chunks) == len(metadata) and all(
            item.get("document_id") == chunk.get("document_id")
            and item.get("embedding_text_sha256") == hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
            for chunk, item in zip(chunks, metadata)
        ),
        "no_nan_or_inf": bool(np.isfinite(embeddings).all()),
        "no_zero_vectors": bool(np.all(np.linalg.norm(embeddings, axis=1) > 0)),
        "normalized": bool(np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-5)),
        "model_matches_manifest": manifest.get("model_name") == MODEL_NAME,
        "input_fingerprint_matches": manifest.get("input_sha256") == sha256_file(chunks_path),
        "linked_metadata_preserved": len(chunks) == len(metadata) and all(
            all(item.get(field) == chunk.get(field) for field in LINK_FIELDS)
            for chunk, item in zip(chunks, metadata)
        ),
        "linked_reference_integrity": link_integrity,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"embedding artifact validation failed: {failed}")
    return checks


def validate_link_references(chunks: list[dict[str, Any]]) -> bool:
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    if len(by_id) != len(chunks):
        return False
    for chunk in chunks:
        previous_id = chunk.get("previous_chunk_id")
        next_id = chunk.get("next_chunk_id")
        if previous_id:
            previous = by_id.get(previous_id)
            if previous is None or previous.get("next_chunk_id") != chunk["chunk_id"]:
                return False
        if next_id:
            next_chunk = by_id.get(next_id)
            if next_chunk is None or next_chunk.get("previous_chunk_id") != chunk["chunk_id"]:
                return False
    return True


def choose_device(requested: str) -> torch.device:
    if requested == "cpu":
        return torch.device("cpu")
    available = bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
    if requested == "mps" and not available:
        raise RuntimeError("MPS requested but unavailable")
    return torch.device("mps" if available else "cpu")


def encode_queries(
    questions: list[str], model: Any, tokenizer: Any, device: torch.device, batch_size: int
) -> np.ndarray:
    instructed = [QUERY_INSTRUCTION + question for question in questions]
    lengths = [len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]) for text in instructed]
    if max(lengths, default=0) > 512:
        raise ValueError("query exceeds the 512-token model limit")
    batches: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(instructed), batch_size):
            batch = instructed[start : start + batch_size]
            encoded = tokenizer(batch, padding=True, truncation=False, return_tensors="pt")
            encoded = {key: value.to(device) for key, value in encoded.items()}
            pooled = model(**encoded).last_hidden_state[:, 0]
            pooled = F.normalize(pooled, p=2, dim=1)
            batches.append(pooled.detach().to("cpu", dtype=torch.float32).numpy())
            print(f"Encoded queries {start + 1}-{start + len(batch)}/{len(instructed)}", flush=True)
    return np.concatenate(batches, axis=0)


def top_k_indices(scores: np.ndarray, k: int) -> np.ndarray:
    if scores.ndim != 1:
        raise ValueError("scores must be one-dimensional")
    return np.argsort(-scores, kind="stable")[:k]


def retrieve(
    questions: list[dict[str, str]],
    ground_truth: list[dict[str, str]],
    chunks: list[dict[str, Any]],
    document_embeddings: np.ndarray,
    query_embeddings: np.ndarray,
    k: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    truth_by_id = {row["question_id"]: row for row in ground_truth}
    rows: list[dict[str, Any]] = []
    ranked_ids: dict[str, list[str]] = {}
    for question, query_vector in zip(questions, query_embeddings):
        truth = truth_by_id[question["question_id"]]
        relevant = set(parse_ids(truth["relevant_chunk_ids"]))
        scores = document_embeddings @ query_vector
        indices = top_k_indices(scores, k)
        ranked_ids[question["question_id"]] = [chunks[int(index)]["chunk_id"] for index in indices]
        for rank, index in enumerate(indices, start=1):
            chunk = chunks[int(index)]
            rows.append({
                "question_id": question["question_id"],
                "question": question["question"],
                "category": question["category"],
                "rank": rank,
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "source": chunk["source"],
                "similarity_score": f"{float(scores[index]):.6f}",
                "chunk_text_excerpt": " ".join(chunk["content"].split())[:500],
                "is_relevant": str(chunk["chunk_id"] in relevant).lower(),
                "ground_truth_status": truth["coverage_status"],
            })
    return rows, ranked_ids


def question_metrics(relevant: set[str], ranked: list[str]) -> dict[str, Any]:
    positions = [index + 1 for index, chunk_id in enumerate(ranked[:10]) if chunk_id in relevant]
    return {
        "hit_at_5": bool(any(position <= 5 for position in positions)),
        "hit_at_10": bool(positions),
        "recall_at_5": len({chunk_id for chunk_id in ranked[:5] if chunk_id in relevant}) / len(relevant) if relevant else None,
        "recall_at_10": len({chunk_id for chunk_id in ranked[:10] if chunk_id in relevant}) / len(relevant) if relevant else None,
        "reciprocal_rank_at_10": 1.0 / min(positions) if positions else 0.0,
        "first_relevant_rank": min(positions) if positions else None,
    }


def aggregate_metrics(
    questions: list[dict[str, str]], ground_truth: list[dict[str, str]], ranked_ids: dict[str, list[str]]
) -> dict[str, Any]:
    truth_by_id = {row["question_id"]: row for row in ground_truth}
    per_question: dict[str, dict[str, Any]] = {}
    included: list[str] = []
    excluded: dict[str, str] = {}
    for question in questions:
        qid = question["question_id"]
        truth = truth_by_id[qid]
        relevant = set(parse_ids(truth["relevant_chunk_ids"]))
        verified = as_bool(truth["ground_truth_verified"])
        if not verified or truth["coverage_status"] == "UNVERIFIED":
            excluded[qid] = "unverified ground truth"
            continue
        if truth["coverage_status"] == "NOT_COVERED":
            excluded[qid] = "no relevant local chunk; evaluated separately as an evidence-gap control"
            continue
        if not relevant:
            excluded[qid] = "verified relevance set is empty"
            continue
        metric = question_metrics(relevant, ranked_ids[qid])
        metric["category"] = question["category"]
        per_question[qid] = metric
        included.append(qid)

    def summarize(ids: list[str]) -> dict[str, Any]:
        if not ids:
            return {"questions": 0, "hit_at_5": None, "hit_at_10": None, "recall_at_5": None, "recall_at_10": None, "mrr_at_10": None}
        return {
            "questions": len(ids),
            "hit_at_5": sum(per_question[qid]["hit_at_5"] for qid in ids) / len(ids),
            "hit_at_10": sum(per_question[qid]["hit_at_10"] for qid in ids) / len(ids),
            "recall_at_5": sum(per_question[qid]["recall_at_5"] for qid in ids) / len(ids),
            "recall_at_10": sum(per_question[qid]["recall_at_10"] for qid in ids) / len(ids),
            "mrr_at_10": sum(per_question[qid]["reciprocal_rank_at_10"] for qid in ids) / len(ids),
        }

    categories: dict[str, list[str]] = defaultdict(list)
    for qid in included:
        categories[per_question[qid]["category"]].append(qid)
    return {
        "metric_scope": "verified FULL/PARTIAL questions with non-empty verified-core relevance labels",
        "recall_label": "partial-label recall; relevance judgments are verified core evidence, not exhaustive pooling",
        "included_question_ids": included,
        "excluded_questions": excluded,
        "aggregate": summarize(included),
        "per_category": {category: summarize(ids) for category, ids in sorted(categories.items())},
        "per_question": per_question,
    }


def failure_rows(
    ground_truth: list[dict[str, str]],
    metrics: dict[str, Any],
    ranked_ids: dict[str, list[str]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    truth_by_id = {row["question_id"]: row for row in ground_truth}
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    rows: list[dict[str, Any]] = []
    for qid, item in metrics["per_question"].items():
        if item["hit_at_5"]:
            continue
        cause, explanation, recommendation = FAILURE_GUIDANCE.get(
            qid,
            ("E", "The verified core evidence did not appear in the top five dense results.", "Reranking after broader candidate retrieval"),
        )
        rows.append({
            "question_id": qid,
            "coverage_status": truth_by_id[qid]["coverage_status"],
            "first_relevant_rank": item["first_relevant_rank"] if item["first_relevant_rank"] is not None else "not_in_top_10",
            "hit_at_5": str(item["hit_at_5"]).lower(),
            "hit_at_10": str(item["hit_at_10"]).lower(),
            "likely_cause": cause,
            "retrieval_evidence": ";".join(ranked_ids[qid][:5]),
            "top_1_excerpt": " ".join(chunk_by_id[ranked_ids[qid][0]]["content"].split())[:500],
            "verified_ground_truth_evidence": truth_by_id[qid]["supporting_evidence"],
            "recommended_next_step": recommendation,
            "notes": explanation,
        })
    return rows


def validate_output_schemas(
    results: list[dict[str, Any]], failures: list[dict[str, Any]], expected_questions: int
) -> bool:
    if len(results) != expected_questions * 10:
        return False
    if any(tuple(row) != RESULT_FIELDS for row in results):
        return False
    by_question: dict[str, list[int]] = defaultdict(list)
    for row in results:
        by_question[row["question_id"]].append(int(row["rank"]))
    if len(by_question) != expected_questions:
        return False
    if any(sorted(ranks) != list(range(1, 11)) for ranks in by_question.values()):
        return False
    if any(tuple(row) != FAILURE_FIELDS for row in failures):
        return False
    return True


def linked_observations(
    ground_truth: list[dict[str, str]], chunks: list[dict[str, Any]], ranked_ids: dict[str, list[str]]
) -> list[dict[str, Any]]:
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    rows: list[dict[str, Any]] = []
    for truth in ground_truth:
        for chunk_id in parse_ids(truth["relevant_chunk_ids"]):
            chunk = chunk_by_id[chunk_id]
            if not chunk.get("requires_context"):
                continue
            linked = [item for item in (chunk.get("previous_chunk_id"), chunk.get("next_chunk_id")) if item]
            rows.append({
                "question_id": truth["question_id"],
                "retrieved_chunk_id": chunk_id if chunk_id in ranked_ids[truth["question_id"]][:10] else "not_retrieved_top_10",
                "relevant_chunk_id": chunk_id,
                "linked_chunk_ids": linked,
                "sufficient_alone": False,
                "adjacent_context_required": True,
                "expansion_may_help": bool(linked),
            })
    return rows


def format_rate(value: Optional[float]) -> str:
    return "n.a." if value is None else f"{value:.3f}"


def write_report(
    path: Path,
    *,
    questions: list[dict[str, str]],
    ground_truth_summary: dict[str, Any],
    artifact_checks: dict[str, bool],
    metrics: dict[str, Any],
    failures: list[dict[str, Any]],
    linked: list[dict[str, Any]],
    device: torch.device,
    elapsed: float,
) -> None:
    aggregate = metrics["aggregate"]
    coverage = ground_truth_summary["coverage"]
    lines = [
        "# HDB Advisory RAG Dense Retrieval Evaluation",
        "",
        "## Evaluation Dataset",
        "",
        f"- Questions: {len(questions)}",
        "- Question IDs: unique",
        "- Empty or duplicate questions: 0",
        f"- Query model: `{MODEL_NAME}` with the model-recommended retrieval instruction",
        f"- Query device: `{device.type.upper()}`",
        f"- Runtime: {elapsed:.2f} seconds",
        "- Baseline: normalized query embedding × existing normalized document embeddings; NumPy cosine similarity; top 10",
        "- ChromaDB, reranking, query decomposition, hybrid search and answer generation: not used",
        "",
        "## Artifact Validation",
        "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} — `{name}`" for name, passed in artifact_checks.items())
    lines.extend([
        "",
        "## Ground Truth",
        "",
        f"- Verified questions: {ground_truth_summary['verified']} / {ground_truth_summary['count']}",
        f"- FULL: {coverage.get('FULL', 0)}",
        f"- PARTIAL: {coverage.get('PARTIAL', 0)}",
        f"- NOT_COVERED: {coverage.get('NOT_COVERED', 0)}",
        f"- UNVERIFIED: {coverage.get('UNVERIFIED', 0)}",
        "- Relevance labels are verified core evidence. They are intentionally not claimed as an exhaustive pool of every duplicate or supporting chunk.",
        "- H29 is retained as a NOT_COVERED evidence-gap control because the knowledge base has no transaction-level resale-price dataset.",
        "",
        "## Dense Retrieval Metrics",
        "",
        f"- Questions included in ordinary retrieval metrics: {aggregate['questions']}",
        f"- Questions excluded: {len(metrics['excluded_questions'])}",
        f"- Hit@5: {format_rate(aggregate['hit_at_5'])}",
        f"- Hit@10: {format_rate(aggregate['hit_at_10'])}",
        f"- Recall@5: {format_rate(aggregate['recall_at_5'])} (partial-label recall)",
        f"- Recall@10: {format_rate(aggregate['recall_at_10'])} (partial-label recall)",
        f"- MRR@10: {format_rate(aggregate['mrr_at_10'])}",
        "",
        "The recall values measure recovery of the reviewed core evidence chunks, not exact recall over every possible relevant chunk.",
        "",
        "## Per-category Performance",
        "",
        "| Category | N | Hit@5 | Hit@10 | Recall@5 | Recall@10 | MRR@10 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for category, item in metrics["per_category"].items():
        safe_category = category.replace("|", "\\|")
        lines.append(
            f"| {safe_category} | {item['questions']} | {format_rate(item['hit_at_5'])} | "
            f"{format_rate(item['hit_at_10'])} | {format_rate(item['recall_at_5'])} | "
            f"{format_rate(item['recall_at_10'])} | {format_rate(item['mrr_at_10'])} |"
        )
    lines.extend([
        "",
        "## Top Retrieval Failure Cases",
        "",
        "Failure codes: E weak semantic similarity; F multi-document; G multiple conditions; H insufficient query specificity.",
        "",
        "| Question | First relevant rank | Cause | Observation | Recommended next step |",
        "|---|---:|---|---|---|",
    ])
    for row in failures:
        lines.append(
            f"| {row['question_id']} | {row['first_relevant_rank']} | {row['likely_cause']} | "
            f"{row['notes']} | "
            f"{row['recommended_next_step']} |"
        )
    lines.extend([
        "",
        "## Linked-chunk Observations",
        "",
        f"- Relevant linked chunks reviewed: {len(linked)}",
        f"- Relevant linked chunks retrieved in top 10: {sum(row['retrieved_chunk_id'] != 'not_retrieved_top_10' for row in linked)}",
        "- Linked evidence should remain separately embedded. At answer time, adjacent expansion can restore conditions or table/legal continuation without changing the dense baseline.",
        "",
        "| Question | Relevant chunk | Retrieved in top 10 | Linked chunks | Sufficient alone | Adjacent context required | Expansion may help |",
        "|---|---|---|---|---|---|---|",
    ])
    for row in linked:
        retrieved = "yes" if row["retrieved_chunk_id"] != "not_retrieved_top_10" else "no"
        linked_ids = ";".join(row["linked_chunk_ids"]) or "none"
        lines.append(
            f"| {row['question_id']} | `{row['relevant_chunk_id']}` | {retrieved} | {linked_ids} | "
            f"{str(row['sufficient_alone']).lower()} | {str(row['adjacent_context_required']).lower()} | "
            f"{str(row['expansion_may_help']).lower()} |"
        )
    lines.extend([
        "",
        "## Recommendations for Advanced RAG",
        "",
        "1. Add reranking over a broader dense candidate set for semantically weak but authoritative policy chunks.",
        "2. Decompose multi-condition and multi-document questions, especially loan comparisons, stamp duties and personalized option reviews.",
        "3. Add hybrid lexical retrieval for exact policy terms, statutory labels, grant names and tax acronyms.",
        "4. Expand previous/next linked chunks after retrieval when `requires_context` is true.",
        "5. Keep H29 as an insufficient-evidence test until a governed transaction dataset is added.",
        "6. Expand relevance judgments through pooled human review before presenting recall as exhaustive ground-truth recall.",
        "",
        "## Limitations",
        "",
        "- This evaluates retrieval, not generated answer correctness, completeness or safety.",
        "- Coverage describes the current local policy corpus; missing user facts are tracked separately.",
        "- Recall is partial-label recall because the verified labels identify core evidence rather than every duplicative relevant chunk.",
        "- No external websites were used to fill local knowledge gaps.",
        "",
        "## Conclusion",
        "",
        "The evaluation pipeline and embedding alignment passed. Source coverage, retrieval performance and answer quality remain distinct: a FULL policy label does not guarantee top-k retrieval, and top-k retrieval does not prove a correct final answer.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("evaluation/HDB_RAG_Integrated_40Q_Evaluation.csv"))
    parser.add_argument("--ground-truth", type=Path, default=Path("evaluation/ground_truth_40q.csv"))
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.jsonl"))
    parser.add_argument("--embedding-dir", type=Path, default=Path("data/embeddings/bge-base-en-v1.5"))
    parser.add_argument("--results", type=Path, default=Path("evaluation/dense_retrieval_results_40q.csv"))
    parser.add_argument("--metrics", type=Path, default=Path("evaluation/dense_retrieval_metrics.json"))
    parser.add_argument("--report", type=Path, default=Path("reports/dense_retrieval_evaluation.md"))
    parser.add_argument("--failures", type=Path, default=Path("reports/retrieval_failure_analysis.csv"))
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    questions = read_csv(args.questions)
    question_checks = validate_questions(questions)
    chunks = read_jsonl(args.chunks)
    metadata = read_jsonl(args.embedding_dir / "metadata.jsonl")
    embeddings = np.load(args.embedding_dir / "embeddings.npy", allow_pickle=False)
    manifest = json.loads((args.embedding_dir / "manifest.json").read_text(encoding="utf-8"))
    artifact_checks = validate_embeddings(args.chunks, chunks, embeddings, metadata, manifest)
    ground_truth = read_csv(args.ground_truth)
    ground_truth_summary = validate_ground_truth(questions, ground_truth, chunks)

    device = choose_device(args.device)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=True).eval().to(device)
    query_embeddings = encode_queries(
        [row["question"] for row in questions], model, tokenizer, device, args.batch_size
    )
    rows, ranked_ids = retrieve(questions, ground_truth, chunks, embeddings, query_embeddings, k=10)
    metrics = aggregate_metrics(questions, ground_truth, ranked_ids)
    failures = failure_rows(ground_truth, metrics, ranked_ids, chunks)
    linked = linked_observations(ground_truth, chunks, ranked_ids)
    if not validate_output_schemas(rows, failures, len(questions)):
        raise ValueError("generated output schema validation failed")

    write_csv(args.results, rows, RESULT_FIELDS)
    write_csv(args.failures, failures, FAILURE_FIELDS)
    metrics_payload = {
        "pipeline_status": "PASS",
        "question_validation": question_checks,
        "embedding_validation": artifact_checks,
        "ground_truth": ground_truth_summary,
        "model": MODEL_NAME,
        "query_instruction": QUERY_INSTRUCTION,
        "device": device.type,
        "top_k": 10,
        "metrics": metrics,
        "not_covered_evaluation": {
            qid: {"top_10_chunk_ids": ranked_ids[qid], "ordinary_retrieval_failure": False}
            for qid, reason in metrics["excluded_questions"].items()
            if "evidence-gap" in reason
        },
        "linked_chunk_observations": linked,
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elapsed = time.perf_counter() - started
    write_report(
        args.report,
        questions=questions,
        ground_truth_summary=ground_truth_summary,
        artifact_checks=artifact_checks,
        metrics=metrics,
        failures=failures,
        linked=linked,
        device=device,
        elapsed=elapsed,
    )
    print(json.dumps({
        "status": "PASS",
        "questions": len(questions),
        "verified_ground_truth": ground_truth_summary["verified"],
        "coverage": ground_truth_summary["coverage"],
        "metrics": metrics["aggregate"],
        "excluded": metrics["excluded_questions"],
        "failure_rows": len(failures),
        "linked_observations": len(linked),
        "device": device.type,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
