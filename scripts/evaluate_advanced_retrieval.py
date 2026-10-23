"""Evaluate P5 advanced retrieval against P4's verified 40-question benchmark.

Advanced retrieval:
- BM25
- query rewriting / re-query
- BGE dense retrieval
- Reciprocal Rank Fusion (RRF)

Uses the same questions, verified ground truth, embeddings and metric functions
as scripts/evaluate_dense_retrieval.py so results are directly comparable.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
from transformers import AutoModel, AutoTokenizer

from chunk_adapter import load_chunks_jsonl
from hybrid_retriever import hybrid_retrieve
from retrieval import search_with_requery

from scripts.evaluate_dense_retrieval import (
    MODEL_NAME,
    QUERY_INSTRUCTION,
    aggregate_metrics,
    choose_device,
    encode_queries,
    parse_ids,
    read_csv,
    read_jsonl,
    top_k_indices,
    validate_embeddings,
    validate_ground_truth,
    validate_questions,
    write_csv,
)


RESULT_FIELDS = [
    "question_id",
    "question",
    "category",
    "final_query",
    "requeried",
    "rewrite_accepted",
    "rank",
    "chunk_id",
    "document_id",
    "source",
    "rrf_score",
    "dense_score",
    "is_relevant",
    "ground_truth_status",
]

DEV_IDS = {
    "H01", "H03", "H05", "H07", "H09",
    "H11", "H13", "H15", "H17", "H19",
    "H21", "H23", "H25", "H27", "H30",
    "C01", "C03", "C05", "C07", "C09",
}

TEST_IDS = {
    "H02", "H04", "H06", "H08", "H10",
    "H12", "H14", "H16", "H18", "H20",
    "H22", "H24", "H26", "H28",
    "C02", "C04", "C06", "C08", "C10",
}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("evaluation/HDB_RAG_Integrated_40Q_Evaluation.csv"),
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=Path("evaluation/ground_truth_40q.csv"),
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=Path("data/processed/chunks.jsonl"),
    )
    parser.add_argument(
        "--embedding-dir",
        type=Path,
        default=Path("data/embeddings/bge-base-en-v1.5"),
    )
    parser.add_argument(
        "--baseline-metrics",
        type=Path,
        default=Path("evaluation/dense_retrieval_metrics.json"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("evaluation/advanced_retrieval_results_40q.csv"),
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path("evaluation/advanced_retrieval_metrics.json"),
    )
    parser.add_argument(
        "--device",
        choices=("auto", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--bm25-weight",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--dense-weight",
        type=float,
        default=1.0,
    )

    return parser.parse_args(argv)

def subset_metrics(per_question, ids):
    rows = [
        per_question[qid]
        for qid in ids
        if qid in per_question
    ]

    if not rows:
        return {}

    return {
        "questions": len(rows),
        "hit_at_5": sum(
            float(row["hit_at_5"])
            for row in rows
        ) / len(rows),
        "hit_at_10": sum(
            float(row["hit_at_10"])
            for row in rows
        ) / len(rows),
        "recall_at_5": sum(
            row["recall_at_5"]
            for row in rows
        ) / len(rows),
        "recall_at_10": sum(
            row["recall_at_10"]
            for row in rows
        ) / len(rows),
        "mrr_at_10": sum(
            row["reciprocal_rank_at_10"]
            for row in rows
        ) / len(rows),
    }

def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()

    # --------------------------------------------------
    # Load and validate exactly the same benchmark assets
    # used by P4's dense baseline.
    # --------------------------------------------------

    questions = read_csv(args.questions)
    question_checks = validate_questions(questions)

    raw_chunks = read_jsonl(args.chunks)
    policies = load_chunks_jsonl(args.chunks)

    metadata = read_jsonl(
        args.embedding_dir / "metadata.jsonl"
    )
    embeddings = np.load(
        args.embedding_dir / "embeddings.npy",
        allow_pickle=False,
    )
    manifest = json.loads(
        (args.embedding_dir / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    artifact_checks = validate_embeddings(
        args.chunks,
        raw_chunks,
        embeddings,
        metadata,
        manifest,
    )

    ground_truth = read_csv(args.ground_truth)

    ground_truth_summary = validate_ground_truth(
        questions,
        ground_truth,
        raw_chunks,
    )

    truth_by_id = {
        row["question_id"]: row
        for row in ground_truth
    }

    policy_by_chunk_id = {
        row["chunk_id"]: row
        for row in policies
    }

    # --------------------------------------------------
    # Stage 1: P5 BM25 + re-query.
    #
    # We first determine each question's final query.
    # Then all final queries are encoded together so BGE
    # is loaded only once.
    # --------------------------------------------------

    retrieval_outputs = []

    for question in questions:
        output = search_with_requery(
            query=question["question"],
            policies=policies,
            query_date=None,
            top_k=args.top_k,
        )
        retrieval_outputs.append(output)

    final_queries = [
        output["final_query"]
        for output in retrieval_outputs
    ]

    # --------------------------------------------------
    # Stage 2: Batch BGE encoding using P4's exact method.
    # --------------------------------------------------

    device = choose_device(args.device)

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        local_files_only=True,
    )

    model = (
        AutoModel.from_pretrained(
            MODEL_NAME,
            local_files_only=True,
        )
        .eval()
        .to(device)
    )

    query_embeddings = encode_queries(
        final_queries,
        model,
        tokenizer,
        device,
        args.batch_size,
    )

    # --------------------------------------------------
    # Stage 3: Dense top-k + BM25 top-k + RRF.
    # --------------------------------------------------

    ranked_ids = {}
    result_rows = []

    for question, output, query_vector in zip(
        questions,
        retrieval_outputs,
        query_embeddings,
    ):
        qid = question["question_id"]
        truth = truth_by_id[qid]

        relevant = set(
            parse_ids(truth["relevant_chunk_ids"])
        )

        dense_scores = embeddings @ query_vector
        dense_indices = top_k_indices(
            dense_scores,
            args.top_k,
        )

        dense_results = []

        for index in dense_indices:
            raw_chunk = raw_chunks[int(index)]
            chunk_id = raw_chunk["chunk_id"]

            policy = dict(
                policy_by_chunk_id[chunk_id]
            )
            policy["dense_score"] = float(
                dense_scores[int(index)]
            )

            dense_results.append(policy)

        if output.get("rewrite_accepted"):
            fused_results = hybrid_retrieve(
                bm25_results=output["results"],
                dense_results=dense_results,
                top_k=args.top_k,
                bm25_weight=1.0,
                dense_weight=1.0,
            )
        else:
            fused_results = dense_results[:args.top_k]

        ranked_ids[qid] = [
            row["chunk_id"]
            for row in fused_results
        ]

        for rank, row in enumerate(
            fused_results,
            start=1,
        ):
            result_rows.append(
                {
                    "question_id": qid,
                    "question": question["question"],
                    "category": question["category"],
                    "final_query": output["final_query"],
                    "requeried": output["requeried"],
                    "rewrite_accepted": output[
                        "rewrite_accepted"
                    ],
                    "rank": rank,
                    "chunk_id": row.get("chunk_id"),
                    "document_id": row.get(
                        "document_id"
                    ),
                    "source": row.get("source"),
                    "rrf_score": (
                        f"{float(row.get('rrf_score', 0.0)):.6f}"
                    ),
                    "dense_score": (
                        ""
                        if row.get("dense_score") is None
                        else f"{float(row['dense_score']):.6f}"
                    ),
                    "is_relevant": str(
                        row.get("chunk_id") in relevant
                    ).lower(),
                    "ground_truth_status": truth[
                        "coverage_status"
                    ],
                }
            )

    # --------------------------------------------------
    # Stage 4: Exact same metrics as P4 dense baseline.
    # --------------------------------------------------

    metrics = aggregate_metrics(
        questions,
        ground_truth,
        ranked_ids,
    )

    baseline_payload = json.loads(
        args.baseline_metrics.read_text(
            encoding="utf-8"
        )
    )

    baseline = baseline_payload["metrics"][
        "aggregate"
    ]
    advanced = metrics["aggregate"]

    baseline_per_question = baseline_payload[
        "metrics"
    ]["per_question"]

    advanced_per_question = metrics[
        "per_question"
    ]

    baseline_dev = subset_metrics(
        baseline_per_question,
        DEV_IDS,
    )

    advanced_dev = subset_metrics(
        advanced_per_question,
        DEV_IDS,
    )

    baseline_test = subset_metrics(
        baseline_per_question,
        TEST_IDS,
    )

    advanced_test = subset_metrics(
        advanced_per_question,
        TEST_IDS,
    )

    metric_names = [
        "hit_at_5",
        "hit_at_10",
        "recall_at_5",
        "recall_at_10",
        "mrr_at_10",
    ]

    delta = {
        name: advanced[name] - baseline[name]
        for name in metric_names
    }

    rewrite_attempts = sum(
        bool(output.get("requeried"))
        for output in retrieval_outputs
    )

    rewrite_accepted = sum(
        bool(output.get("rewrite_accepted"))
        for output in retrieval_outputs
    )

    payload = {
        "pipeline_status": "PASS",
        "system": (
            "P5 advanced retrieval: "
            "BM25 + query rewriting + BGE + RRF"
        ),
        "question_validation": question_checks,
        "embedding_validation": artifact_checks,
        "ground_truth": ground_truth_summary,
        "model": MODEL_NAME,
        "query_instruction": QUERY_INSTRUCTION,
        "device": device.type,
        "top_k": args.top_k,
        "query_rewriting": {
            "questions": len(questions),
            "requery_attempts": rewrite_attempts,
            "rewrites_accepted": rewrite_accepted,
        },
        "metrics": metrics,
        "dense_baseline": baseline,
        "delta_vs_dense_baseline": delta,
        "weights": {
            "bm25": args.bm25_weight,
            "dense": args.dense_weight,
        },
        "development_split": {
            "baseline": baseline_dev,
            "advanced": advanced_dev,
        },
        "test_split": {
            "baseline": baseline_test,
            "advanced": advanced_test,
        },
    }

    # --------------------------------------------------
    # Save outputs.
    # --------------------------------------------------

    write_csv(
        args.results,
        result_rows,
        RESULT_FIELDS,
    )

    args.metrics.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.metrics.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    elapsed = time.perf_counter() - started

    print("\n========================================")
    print("P5 ADVANCED RETRIEVAL EVALUATION")
    print("========================================")

    print(
        f"Questions evaluated: "
        f"{advanced['questions']}"
    )

    for name in metric_names:
        print(
            f"{name}: "
            f"{baseline[name]:.3f} -> "
            f"{advanced[name]:.3f} "
            f"(delta {delta[name]:+.3f})"
        )

    print(
        f"Re-query attempts: {rewrite_attempts}"
    )
    print(
        f"Rewrites accepted: {rewrite_accepted}"
    )
    print(
        f"Elapsed seconds: {elapsed:.2f}"
    )

    print(
        f"\nResults: {args.results}"
    )
    print(
        f"Metrics: {args.metrics}"
    )

    print("\nDEVELOPMENT SPLIT")
    for name in metric_names:
        print(
            f"{name}: "
            f"{baseline_dev[name]:.3f} -> "
            f"{advanced_dev[name]:.3f}"
        )

    print("\nTEST SPLIT")
    for name in metric_names:
        print(
            f"{name}: "
            f"{baseline_test[name]:.3f} -> "
            f"{advanced_test[name]:.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())