#!/usr/bin/env python3
"""Compare Stage 8 Chroma retrieval against the unchanged Stage 7 NumPy baseline."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
from transformers import AutoModel, AutoTokenizer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.chroma_db import COLLECTION_NAME, MODEL_NAME, get_collection, load_and_validate_artifacts, persistent_client, validate_collection_identity, validate_existing_records, collection_metadata
from scripts.evaluate_dense_retrieval import aggregate_metrics, choose_device, encode_queries, read_csv, top_k_indices, validate_ground_truth, validate_questions


FIELDS = (
    "question_id", "numpy_top10_ids", "chroma_top10_ids", "top5_set_match",
    "top10_set_match", "rank_order_match", "score_difference", "notes",
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("evaluation/HDB_RAG_Integrated_40Q_Evaluation.csv"))
    parser.add_argument("--ground-truth", type=Path, default=Path("evaluation/ground_truth_40q.csv"))
    parser.add_argument("--baseline-metrics", type=Path, default=Path("evaluation/dense_retrieval_metrics.json"))
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.jsonl"))
    parser.add_argument("--embedding-dir", type=Path, default=Path("data/embeddings/bge-base-en-v1.5"))
    parser.add_argument("--persist-directory", type=Path, default=Path("data/vector_db/chroma"))
    parser.add_argument("--collection-name", default=COLLECTION_NAME)
    parser.add_argument("--output", type=Path, default=Path("reports/chroma_vs_numpy_consistency.csv"))
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    return parser.parse_args(argv)


def compare_rankings(
    questions: list[dict[str, str]], chunks: list[dict[str, Any]], vectors: np.ndarray,
    query_vectors: np.ndarray, collection: Any,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, list[str]], float]:
    chroma_result = collection.query(
        query_embeddings=query_vectors.tolist(),
        n_results=10,
        include=["distances"],
    )
    rows: list[dict[str, Any]] = []
    numpy_ranked: dict[str, list[str]] = {}
    chroma_ranked: dict[str, list[str]] = {}
    maximum_difference = 0.0
    for q_index, question in enumerate(questions):
        numpy_scores = vectors @ query_vectors[q_index]
        indices = top_k_indices(numpy_scores, 10)
        numpy_ids = [chunks[int(index)]["chunk_id"] for index in indices]
        numpy_by_id = {chunks[int(index)]["chunk_id"]: float(numpy_scores[index]) for index in indices}
        chroma_ids = list(chroma_result["ids"][q_index])
        chroma_by_id = {
            chunk_id: 1.0 - float(distance)
            for chunk_id, distance in zip(chroma_ids, chroma_result["distances"][q_index])
        }
        common = set(numpy_by_id) & set(chroma_by_id)
        difference = max((abs(numpy_by_id[item] - chroma_by_id[item]) for item in common), default=0.0)
        maximum_difference = max(maximum_difference, difference)
        top5_match = set(numpy_ids[:5]) == set(chroma_ids[:5])
        top10_match = set(numpy_ids) == set(chroma_ids)
        rank_match = numpy_ids == chroma_ids
        notes = "identical top-10 order" if rank_match else "HNSW approximate ranking differs from exact NumPy order"
        rows.append({
            "question_id": question["question_id"],
            "numpy_top10_ids": ";".join(numpy_ids),
            "chroma_top10_ids": ";".join(chroma_ids),
            "top5_set_match": str(top5_match).lower(),
            "top10_set_match": str(top10_match).lower(),
            "rank_order_match": str(rank_match).lower(),
            "score_difference": f"{difference:.10f}",
            "notes": notes,
        })
        numpy_ranked[question["question_id"]] = numpy_ids
        chroma_ranked[question["question_id"]] = chroma_ids
    return rows, numpy_ranked, chroma_ranked, maximum_difference


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    bundle = load_and_validate_artifacts(args.chunks, args.embedding_dir)
    questions = read_csv(args.questions)
    ground_truth = read_csv(args.ground_truth)
    validate_questions(questions)
    validate_ground_truth(questions, ground_truth, bundle.chunks)
    baseline_payload = json.loads(args.baseline_metrics.read_text(encoding="utf-8"))
    baseline_before = args.baseline_metrics.read_bytes()

    client = persistent_client(args.persist_directory)
    collection = get_collection(client, args.collection_name)
    validate_collection_identity(collection, collection_metadata(bundle, str(args.embedding_dir / "manifest.json")))
    validate_existing_records(collection, bundle, include_embeddings=True)

    device = choose_device(args.device)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=True).eval().to(device)
    query_vectors = encode_queries([item["question"] for item in questions], model, tokenizer, device, args.batch_size)
    if query_vectors.shape != (40, bundle.embeddings.shape[1]) or not np.allclose(np.linalg.norm(query_vectors, axis=1), 1.0, atol=1e-5):
        raise ValueError("query embedding compatibility validation failed")

    rows, numpy_ranked, chroma_ranked, max_difference = compare_rankings(
        questions, bundle.chunks, bundle.embeddings, query_vectors, collection
    )
    numpy_metrics = aggregate_metrics(questions, ground_truth, numpy_ranked)
    chroma_metrics = aggregate_metrics(questions, ground_truth, chroma_ranked)
    if args.baseline_metrics.read_bytes() != baseline_before:
        raise ValueError("baseline metrics file changed during Stage 8 validation")
    recorded = baseline_payload["metrics"]["aggregate"]
    if any(abs(float(numpy_metrics["aggregate"][key]) - float(recorded[key])) > 1e-12 for key in recorded if key != "questions"):
        raise ValueError("fresh NumPy metrics do not match the recorded Stage 7 baseline")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "PASS" if all(row["top10_set_match"] == "true" for row in rows) else "PASS_WITH_WARNINGS",
        "questions": len(rows),
        "top5_set_matches": sum(row["top5_set_match"] == "true" for row in rows),
        "top10_set_matches": sum(row["top10_set_match"] == "true" for row in rows),
        "exact_rank_order_matches": sum(row["rank_order_match"] == "true" for row in rows),
        "maximum_common_id_score_difference": max_difference,
        "numpy_metrics": numpy_metrics["aggregate"],
        "chroma_metrics": chroma_metrics["aggregate"],
        "device": device.type,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
