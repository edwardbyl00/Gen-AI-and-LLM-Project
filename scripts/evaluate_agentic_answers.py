import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dense_retriever import dense_retrieve
from policy_agent import run_policy_agent
from llm_judge import judge_answer
from agents.supervisor.synthesis import synthesise

from ground_truth_judge import (
    judge_against_ground_truth,
)


PILOT_IDS = ["H01", "H07", "H14", "H15", "H23", "H29", "C01", "C04", "C06", "C10",]

def parse_ids(value):
    return {
        x.strip()
        for x in (value or "").split(";")
        if x.strip()
    }


def make_bundle(
    question,
    evidence,
    decision=None,
    reason=None,
):
    return {
        "question": question,
        "today": "2026-10-23",
        "routing": {
            "route": "policy",
            "false_belief": False,
            "answerable": True,
            "reason": "Policy evaluation benchmark.",
        },
        "price_result": None,
        "policy_result": {
            "evidence": evidence,
            "decision": decision,
            "reason": reason,
        },
        "agent_errors": {},
        "steps": [],
    }


def evidence_overlap(evidence, gold_ids):
    retrieved = {
        item.get("chunk_id")
        for item in evidence
        if item.get("chunk_id")
    }

    overlap = sorted(retrieved & gold_ids)

    recall = (
        len(overlap) / len(gold_ids)
        if gold_ids
        else None
    )

    return {
        "retrieved_chunk_ids": sorted(retrieved),
        "gold_overlap": overlap,
        "gold_recall": recall,
    }


def generate_baseline(question):
    """
    V0:
    BGE dense top-10 -> synthesis.

    No evidence assessor.
    No decomposition.
    No abstention gate before synthesis.
    """
    started = time.perf_counter()

    evidence = dense_retrieve(
        question,
        top_k=10,
    )

    bundle = make_bundle(
        question=question,
        evidence=evidence,
        decision="ANSWER_READY",
        reason=(
            "Dense retrieval baseline; "
            "no evidence assessment."
        ),
    )

    answer = synthesise(bundle)

    latency = time.perf_counter() - started

    return {
        "decision": "ANSWER_READY",
        "reason": (
            "Baseline has no pre-synthesis "
            "abstention gate."
        ),
        "evidence": evidence,
        "answer": answer,
        "latency_seconds": round(latency, 3),
    }


def generate_agentic(question):
    """
    V1:
    Retrieval -> evidence assessment ->
    targeted decomposition/self-correction ->
    reassessment -> answer or abstain.
    """
    started = time.perf_counter()

    agent = run_policy_agent(
        question,
        top_k=10,
        use_dense=True,
        use_llm_assessor=True,
    )

    decision = agent["decision"]

    evidence = (
        agent["retrieval"]["evidence"]
        if decision == "ANSWER_READY"
        else []
    )

    bundle = make_bundle(
        question=question,
        evidence=evidence,
        decision=decision,
        reason=agent["reason"],
    )

    answer = synthesise(bundle)

    latency = time.perf_counter() - started

    return {
        "decision": decision,
        "reason": agent["reason"],
        "evidence": evidence,
        "answer": answer,
        "trace": agent["trace"],
        "latency_seconds": round(latency, 3),
        "assessor_usage": agent.get(
            "assessor_usage",
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "latency_seconds": 0.0,
            },
        ),
    }


def run_judge(question, system_result):
    started = time.perf_counter()

    result = judge_answer(
        question=question,
        answer=system_result["answer"]["answer"],
        evidence=system_result["evidence"],
    )

    result["latency_seconds"] = round(
        time.perf_counter() - started,
        3,
    )

    return result

def run_ground_truth_judge(
    row,
    system_result,
):
    started = time.perf_counter()

    result = judge_against_ground_truth(
        question=row["question"],
        answer=system_result[
            "answer"
        ]["answer"],
        decision=system_result[
            "decision"
        ],
        declined=system_result[
            "answer"
        ]["declined"],
        evidence=system_result[
            "evidence"
        ],
        coverage_status=row[
            "coverage_status"
        ],
        supporting_evidence=row[
            "supporting_evidence"
        ],
        required_conditions=row[
            "required_conditions"
        ],
        review_notes=row.get(
            "review_notes",
            "",
        ),
    )

    result["latency_seconds"] = round(
        time.perf_counter() - started,
        3,
    )

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run paid LLM-as-judge calls.",
    )
    args = parser.parse_args()

    ground_truth_path = (
        PROJECT_ROOT
        / "evaluation"
        / "retrieval"
        / "ground_truth_40q.csv"
    )

    with ground_truth_path.open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        all_rows = {
            row["question_id"]: row
            for row in csv.DictReader(f)
        }

    results = []

    for qid in PILOT_IDS:
        row = all_rows[qid]
        question = row["question"]
        gold_ids = parse_ids(
            row["relevant_chunk_ids"]
        )

        print("\n" + "=" * 70)
        print(qid, question)
        print("=" * 70)

        baseline = generate_baseline(question)
        agentic = generate_agentic(question)

        baseline["retrieval_eval"] = (
            evidence_overlap(
                baseline["evidence"],
                gold_ids,
            )
        )

        agentic["retrieval_eval"] = (
            evidence_overlap(
                agentic["evidence"],
                gold_ids,
            )
        )

        if args.judge:
            print("Running baseline judge...")
            baseline["judge"] = run_judge(
                question,
                baseline,
            )

            print("Running agentic judge...")
            agentic["judge"] = run_judge(
                question,
                agentic,
            )

        print("Running baseline ground-truth judge...")
        baseline["ground_truth_judge"] = (
            run_ground_truth_judge(
                row,
                baseline,
            )
        )

        print("Running agentic ground-truth judge...")
        agentic["ground_truth_judge"] = (
            run_ground_truth_judge(
                row,
                agentic,
            )
        )

        print(
            "BASELINE:",
            "declined=",
            baseline["answer"]["declined"],
            "| gold=",
            baseline["retrieval_eval"][
                "gold_overlap"
            ],
            "| latency=",
            baseline["latency_seconds"],
        )

        print(
            "AGENTIC:",
            "decision=",
            agentic["decision"],
            "| declined=",
            agentic["answer"]["declined"],
            "| gold=",
            agentic["retrieval_eval"][
                "gold_overlap"
            ],
            "| latency=",
            agentic["latency_seconds"],
            "| assessor_calls=",
            agentic["assessor_usage"]["calls"],
            "| assessor_tokens=",
            agentic["assessor_usage"]["total_tokens"],
            "| assessor_latency=",
            agentic["assessor_usage"]["latency_seconds"],
        )

        results.append(
            {
                "question_id": qid,
                "question": question,
                "category": row["category"],
                "coverage_status": row[
                    "coverage_status"
                ],
                "gold_chunk_ids": sorted(
                    gold_ids
                ),
                "baseline": baseline,
                "agentic": agentic,
            }
        )

    suffix = (
        "judged"
        if args.judge
        else "unjudged"
    )

    output = (
        PROJECT_ROOT
        / "evaluation"
        / f"agentic_vs_baseline_pilot_10q_{suffix}.json"
    )

    baseline_latencies = [
        r["baseline"]["latency_seconds"]
        for r in results
    ]

    agentic_latencies = [
        r["agentic"]["latency_seconds"]
        for r in results
    ]

    assessor_usages = [
        r["agentic"]["assessor_usage"]
        for r in results
    ]

    baseline_avg_latency = (
        sum(baseline_latencies) / len(baseline_latencies)
    )

    agentic_avg_latency = (
        sum(agentic_latencies) / len(agentic_latencies)
    )

    total_assessor_calls = sum(
        u["calls"]
        for u in assessor_usages
    )

    total_input_tokens = sum(
        u["input_tokens"]
        for u in assessor_usages
    )

    total_output_tokens = sum(
        u["output_tokens"]
        for u in assessor_usages
    )

    total_assessor_tokens = sum(
        u["total_tokens"]
        for u in assessor_usages
    )

    total_assessor_latency = sum(
        u["latency_seconds"]
        for u in assessor_usages
    )

    efficiency_summary = {
        "questions": len(results),
        "baseline_average_latency_seconds": round(
            baseline_avg_latency,
            3,
        ),
        "agentic_average_latency_seconds": round(
            agentic_avg_latency,
            3,
        ),
        "agentic_latency_overhead_seconds": round(
            agentic_avg_latency - baseline_avg_latency,
            3,
        ),
        "assessor": {
            "total_calls": total_assessor_calls,
            "average_calls_per_question": round(
                total_assessor_calls / len(results),
                3,
            ),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_assessor_tokens,
            "average_tokens_per_question": round(
                total_assessor_tokens / len(results),
                1,
            ),
            "total_latency_seconds": round(
                total_assessor_latency,
                3,
            ),
            "average_latency_seconds_per_question": round(
                total_assessor_latency / len(results),
                3,
            ),
        },
    }

    output.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    efficiency_output = output.with_name(
        output.stem
        + "_efficiency_summary.json"
    )

    efficiency_output.write_text(
        json.dumps(
            efficiency_summary,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print("PILOT COMPLETE")
    print("=" * 70)

    print("Saved:", output)

    print("Saved:", efficiency_output)

    print(
        "Baseline mean latency:",
        efficiency_summary[
            "baseline_average_latency_seconds"
        ],
    )

    print(
        "Agentic mean latency:",
        efficiency_summary[
            "agentic_average_latency_seconds"
        ],
    )

    print(
        "Agentic latency overhead:",
        efficiency_summary[
            "agentic_latency_overhead_seconds"
        ],
    )

    print(
        "Assessor calls:",
        efficiency_summary[
            "assessor"
        ]["total_calls"],
    )

    print(
        "Assessor total tokens:",
        efficiency_summary[
            "assessor"
        ]["total_tokens"],
    )

    print(
        "Assessor mean tokens/question:",
        efficiency_summary[
            "assessor"
        ]["average_tokens_per_question"],
    )

    print(
        "Assessor mean latency/question:",
        efficiency_summary[
            "assessor"
        ][
            "average_latency_seconds_per_question"
        ],
    )

    print(
        "Agentic ANSWER_READY:",
        sum(
            r["agentic"]["decision"]
            == "ANSWER_READY"
            for r in results
        ),
        "/",
        len(results),
    )

    print(
        "Agentic ABSTAIN:",
        sum(
            r["agentic"]["decision"]
            == "ABSTAIN"
            for r in results
        ),
        "/",
        len(results),
    )

    if args.judge:
        baseline_scores = [
            r["baseline"]["judge"][
                "judgement"
            ]["total_score"]
            for r in results
        ]

        agentic_scores = [
            r["agentic"]["judge"][
                "judgement"
            ]["total_score"]
            for r in results
        ]

        baseline_cost = sum(
            r["baseline"]["judge"]["usage"][
                "cost_usd"
            ]
            for r in results
        )

        agentic_cost = sum(
            r["agentic"]["judge"]["usage"][
                "cost_usd"
            ]
            for r in results
        )

        print(
            "Baseline mean judge:",
            round(
                sum(baseline_scores)
                / len(baseline_scores),
                3,
            ),
        )

        print(
            "Agentic mean judge:",
            round(
                sum(agentic_scores)
                / len(agentic_scores),
                3,
            ),
        )

        print(
            "Judge cost USD:",
            round(
                baseline_cost
                + agentic_cost,
                4,
            ),
        )

        baseline_gt_scores = [
            r["baseline"][
                "ground_truth_judge"
            ]["judgement"]["total_score"]
            for r in results
        ]

        agentic_gt_scores = [
            r["agentic"][
                "ground_truth_judge"
            ]["judgement"]["total_score"]
            for r in results
        ]

        print(
            "Baseline mean ground-truth judge:",
            round(
                sum(baseline_gt_scores)
                / len(baseline_gt_scores),
                3,
            ),
        )

        print(
            "Agentic mean ground-truth judge:",
            round(
                sum(agentic_gt_scores)
                / len(agentic_gt_scores),
                3,
            ),
        )


if __name__ == "__main__":
    main()