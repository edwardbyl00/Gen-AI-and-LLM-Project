"""Paired end-to-end A/B runs on question-only CSVs; no reference answers enter inference."""

import argparse
import csv
import hashlib
import json
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from agents.supervisor.pipeline import handle_question
from agents.supervisor.router import CONFIG_FILE, PROJECT_ROOT, estimate_cost_usd
from agents.supervisor.synthesis import format_answer

VARIANTS = {"A_baseline": False, "B_decomposition": True}
GRADES = ("correctness", "completeness", "groundedness", "appropriate_abstention")
PIPELINES = {
    "supervisor": "Supervisor handle_question: routing, agents and synthesis; excludes P3 graph/self-check",
    "graph": "P3 graph: supervisor routing, parallel agent branches, synthesis and bounded self-check",
}


def select_pipeline(name):
    if name == "graph":
        from agents.graph.graph import run
        return run
    if name == "supervisor":
        return handle_question
    raise ValueError(f"Unknown pipeline: {name}")


def fingerprint(path):
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_questions(path):
    """Whitelist inference inputs. Other columns (including gold answers) are ignored."""
    with open(path, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    questions, seen = [], set()
    for row in rows:
        qid, question = (row.get("question_id") or "").strip(), (row.get("question") or "").strip()
        if not qid or not question or qid in seen:
            raise ValueError("Require nonempty, unique question_id and nonempty question")
        seen.add(qid)
        questions.append({"question_id": qid, "question": question,
                          "category": (row.get("category") or "unspecified").strip()})
    if not questions:
        raise ValueError("Question file is empty")
    return questions


def write_csv(path, rows, columns):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(records):
    """Retain failures in denominators; grades are supplied independently later."""
    groups = defaultdict(list)
    for row in records:
        groups[(row["variant"], "all")].append(row)
        groups[(row["variant"], "category:" + row["category"])].append(row)
    summaries = []
    for (variant, group), rows in sorted(groups.items()):
        values = lambda key: [r[key] for r in rows if r.get(key) is not None]
        summary = {"variant": variant, "group": group, "runs": len(rows),
                   "pipeline_errors": sum(bool(r.get("error")) for r in rows),
                   "agent_error_runs": sum(bool(r.get("bundle", {}).get("agent_errors")) for r in rows),
                   "synthesis_error_runs": sum(any(s["step"] == "synthesis" and s.get("error")
                       for s in r.get("bundle", {}).get("steps", [])) for r in rows),
                   "router_fallback_runs": sum(
                       r.get("bundle", {}).get("routing", {}).get("reason", "").startswith(
                           "Router output could not be read") for r in rows),
                   "usage_incomplete_runs": sum(r["usage_incomplete"] for r in rows),
                   "weak_self_check_runs": sum(r.get("bundle", {}).get("self_check", {}).get(
                       "verdict") == "weak" for r in rows),
                   "self_check_error_runs": sum(any(s["step"] == "self_check" and s.get("error")
                       for s in r.get("bundle", {}).get("steps", [])) for r in rows),
                   "total_recorded_cost_usd": round(sum(values("cost_usd")), 6)}
        for key in ("seconds", "input_tokens", "output_tokens", "model_calls", "cost_usd"):
            vals = values(key)
            summary["mean_" + key] = statistics.mean(vals) if vals else None
            summary["stdev_" + key] = statistics.stdev(vals) if len(vals) > 1 else None
            summary["median_" + key] = statistics.median(vals) if vals else None
        summaries.append(summary)
    return summaries


def run_experiment(questions, out_dir, today, repeats=1, seed=42, answer_fn=None,
                   pipeline="supervisor"):
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if pipeline not in PIPELINES:
        raise ValueError(f"Unknown pipeline: {pipeline}")
    answer_fn = answer_fn or select_pipeline(pipeline)
    settings = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    if settings.get("agents", {}).get("policy") != "real":
        raise ValueError("End-to-end evaluation requires agents.policy: real")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    paths = list((PROJECT_ROOT / "agents").rglob("*.py")) + list((PROJECT_ROOT / "agents").rglob("*.md"))
    paths += list((PROJECT_ROOT / "src").rglob("*.py")) + [CONFIG_FILE]
    paths += [PROJECT_ROOT / "data/processed/chunks.jsonl",
              PROJECT_ROOT / "data/cleaned/deduplicated_documents.jsonl"]
    vector_settings = settings.get("data_preparation", {}).get("vector_store", {})
    if vector_settings.get("persist_directory"):
        store = PROJECT_ROOT / vector_settings["persist_directory"]
        paths.extend(p for p in store.rglob("*") if p.is_file())
    for key in ("raw_data", "cleaned_data"):
        value = settings.get("price_agent", {}).get(key)
        if value:
            paths.append(PROJECT_ROOT / value)
    manifest = {"created_at": datetime.now(ZoneInfo("Asia/Singapore")).isoformat(),
                "today": today, "repeats": repeats, "shuffle_seed": seed,
                "variants": VARIANTS, "questions": questions, "config": settings,
                "question_set_sha256": hashlib.sha256(
                    json.dumps(questions, sort_keys=True).encode()).hexdigest(),
                "fingerprints": {str(p.relative_to(PROJECT_ROOT)) if p.is_relative_to(PROJECT_ROOT)
                                 else str(p): fingerprint(p) for p in sorted(set(paths))},
                "pipeline": pipeline, "scope": PIPELINES[pipeline],
                "cost_note": "Configured rates, recorded calls only; unreported SDK retries may be missing"}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    rng = random.Random(seed)
    schedule = []
    for repeat in range(1, repeats + 1):
        for question in questions:
            variants = list(VARIANTS)
            rng.shuffle(variants)
            schedule.extend((repeat, question, variant) for variant in variants)
    records = []
    # Flush each result so interrupted paid runs retain completed calls.
    with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as stream:
        for index, (repeat, question, variant) in enumerate(schedule, 1):
            print(f"[{index}/{len(schedule)}] {question['question_id']} repeat={repeat} {variant}", flush=True)
            start = time.perf_counter()
            record = {**question, "repeat": repeat, "variant": variant, "pipeline": pipeline}
            reported_usage = []
            try:
                bundle = answer_fn(question["question"], today=today, decompose=VARIANTS[variant],
                                   usage_log=reported_usage)
                usage = bundle.get("usage", [])
                record.update(bundle=bundle, error=None,
                              answer=format_answer(bundle["answer"]),
                              input_tokens=sum(u.get("input_tokens") or 0 for u in usage),
                              output_tokens=sum(u.get("output_tokens") or 0 for u in usage),
                              model_calls=sum(u.get("calls", 1) for u in usage),
                              cost_usd=bundle.get("cost_usd"),
                              usage_incomplete=not usage or any(u.get("input_tokens") is None or
                                  u.get("output_tokens") is None for u in usage) or
                                  bool(bundle.get("agent_errors")) or
                                  any(s.get("error") for s in bundle.get("steps", [])))
            except Exception as error:
                record.update(error=f"{type(error).__name__}: {error}", answer="[Pipeline execution failed]",
                              partial_usage=reported_usage,
                              input_tokens=sum(u.get("input_tokens") or 0 for u in reported_usage)
                                  if reported_usage else None,
                              output_tokens=sum(u.get("output_tokens") or 0 for u in reported_usage)
                                  if reported_usage else None,
                              model_calls=sum(u.get("calls", 1) for u in reported_usage)
                                  if reported_usage else None,
                              cost_usd=estimate_cost_usd(reported_usage, settings.get("llm", {}).get("pricing"))
                                  if reported_usage else None, usage_incomplete=True)
            record["seconds"] = round(time.perf_counter() - start, 4)
            record["review_id"] = hashlib.sha256(
                f"{pipeline}:{seed}:{question['question_id']}:{repeat}:{variant}".encode()).hexdigest()[:16]
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            records.append(record)
    blinded = [{"review_id": r["review_id"], "question_id": r["question_id"],
                "question": r["question"], "answer": r["answer"],
                **{g: "" for g in GRADES}, "reviewer_notes": ""} for r in records]
    rng.shuffle(blinded)
    write_csv(out_dir / "grading_blind.csv", blinded,
              ["review_id", "question_id", "question", "answer", *GRADES, "reviewer_notes"])
    write_csv(out_dir / "review_key.csv", [{k: r[k] for k in
              ("review_id", "question_id", "repeat", "variant")} for r in records],
              ["review_id", "question_id", "repeat", "variant"])
    (out_dir / "efficiency.json").write_text(json.dumps(aggregate(records), indent=2), encoding="utf-8")
    return records


def score_experiment(run_dir, grading_path):
    run_dir = Path(run_dir)
    records = [json.loads(line) for line in (run_dir / "runs.jsonl").read_text().splitlines()]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    expected = {(q["question_id"], repeat, variant) for q in manifest["questions"]
                for repeat in range(1, manifest["repeats"] + 1) for variant in manifest["variants"]}
    actual = {(r["question_id"], r["repeat"], r["variant"]) for r in records}
    if actual != expected or len(records) != len(expected):
        raise ValueError("Incomplete or duplicated experiment runs; cannot score")
    with open(grading_path, newline="", encoding="utf-8-sig") as stream:
        grades = list(csv.DictReader(stream))
    by_id = {g["review_id"]: g for g in grades}
    if len(by_id) != len(grades) or set(by_id) != {r["review_id"] for r in records}:
        raise ValueError("Grades must match every run exactly once")
    grouped = defaultdict(list)
    paired = defaultdict(dict)
    for record in records:
        grade = by_id[record["review_id"]]
        for metric in GRADES:
            try:
                value = float(grade[metric])
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError(f"Missing/invalid {metric}: {record['review_id']}") from error
            if not 0 <= value <= 1:
                raise ValueError(f"{metric} must be between 0 and 1")
            if record.get("error") and value != 0:
                raise ValueError("Failed executions must receive zero quality grades")
            grouped[(record["variant"], "all", metric)].append(value)
            grouped[(record["variant"], "category:" + record["category"], metric)].append(value)
            paired[(record["question_id"], record["repeat"], metric)][record["variant"]] = value
    deltas = defaultdict(list)
    for (_, _, metric), pair in paired.items():
        if set(pair) == set(VARIANTS):
            deltas[metric].append(pair["B_decomposition"] - pair["A_baseline"])
    return {"quality": [{"variant": v, "group": group, "metric": metric,
                         "n": len(vals), "mean": statistics.mean(vals)}
                        for (v, group, metric), vals in sorted(grouped.items())],
            "paired_B_minus_A": {metric: {"n_pairs": len(vals), "mean": statistics.mean(vals)}
                                 for metric, vals in deltas.items()},
            "efficiency": aggregate(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("questions", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--today", default=datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat())
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--pipeline", choices=PIPELINES, default="supervisor")
    score = commands.add_parser("score")
    score.add_argument("run_dir", type=Path)
    score.add_argument("grading", type=Path)
    args = parser.parse_args()
    if args.command == "score":
        print(json.dumps(score_experiment(args.run_dir, args.grading), indent=2))
        return
    questions = load_questions(args.questions)
    datetime.strptime(args.today, "%Y-%m-%d")
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.dry_run:
        print(json.dumps({"questions": len(questions), "pipeline_runs": len(questions) * args.repeats * 2,
                          "variants": VARIANTS, "today": args.today,
                          "pipeline": args.pipeline, "scope": PIPELINES[args.pipeline]}, indent=2))
        return
    run_experiment(questions, args.out, args.today, args.repeats, args.seed, pipeline=args.pipeline)
    print(f"Saved {args.out}. Grade grading_blind.csv, then use the score command.")


if __name__ == "__main__":
    main()
