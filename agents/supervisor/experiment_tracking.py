"""MLflow experiment records built from existing results; no LLM evaluation calls."""

import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from agents.supervisor.router import PROJECT_ROOT


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def flatten(value, prefix="config"):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if any(word in key.lower() for word in ("api_key", "password", "secret", "credential", "access_token")):
            result[name] = "[REDACTED]"
        elif isinstance(item, dict):
            result.update(flatten(item, name))
        else:
            text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
            result[name] = text if len(text) < 5000 else "sha256:" + json_hash(item)
    return result


def snapshot_settings(settings):
    """Keep the full configuration artifact, redacting credential-shaped keys."""
    result = {}
    for key, item in settings.items():
        if any(word in key.lower() for word in ("api_key", "password", "secret", "credential", "access_token")):
            result[key] = "[REDACTED]"
        else:
            result[key] = snapshot_settings(item) if isinstance(item, dict) else item
    return result


def provenance():
    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT,
                stderr=subprocess.DEVNULL, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"
    return {"git_commit": git("rev-parse", "HEAD"),
            "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
            "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
                         if d.metadata.get("Name")}}


def resolve_uri(value):
    value = value or os.environ.get("MLFLOW_TRACKING_URI") or "sqlite:///logs/mlflow/mlflow.db"
    if value.startswith("sqlite:///") and value != "sqlite:///:memory:":
        path = Path(value[len("sqlite:///"):])
        path = path if path.is_absolute() else PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return "sqlite:///" + path.resolve().as_posix()
    return value


def effective_params(settings, pipeline, decompose):
    # Store overrides separately from the requested config so baseline A is
    # never mislabeled by config.yaml's default decompose=true.
    review = settings.get("self_check", {})
    selected = {key: settings.get(key, {}) for key in
                ("llm", "supervisor", "self_check", "agents", "price_agent", "data_preparation")}
    selected["supervisor"] = {**selected["supervisor"], "decompose": decompose}
    return {
        "effective.supervisor.decompose": str(decompose).lower(),
        "effective.self_check.llm_check": str(pipeline == "graph" and review.get("llm_check", True)).lower(),
        "effective.self_check.max_retries": str(review.get("max_retries", 1) if pipeline == "graph" else 0),
        "effective.policy_top_k": str(settings.get("agents", {}).get("policy_top_k", 3)),
        "setup_id": json_hash({"pipeline": pipeline, "settings": selected})[:16],
    }


def make_client(uri):
    try:
        from mlflow import MlflowClient
    except ImportError as error:
        raise RuntimeError("MLflow tracking needs: python -m pip install -r requirements-experiments.txt") from error
    return MlflowClient(tracking_uri=uri)


def log_values(client, run_id, *, params=None, metrics=None):
    from mlflow.entities import Metric, Param
    timestamp = int(time.time() * 1000)
    parameters = [Param(k, str(v)) for k, v in (params or {}).items()]
    measures = [Metric(k, float(v), timestamp, 0) for k, v in (metrics or {}).items()
                if isinstance(v, (int, float)) and math.isfinite(v)]
    for offset in range(0, max(len(parameters), len(measures)), 100):
        client.log_batch(run_id, params=parameters[offset:offset + 100],
                         metrics=measures[offset:offset + 100], synchronous=True)


class MLflowBatch:
    def __init__(self, manifest, out_dir, *, tracking_uri=None, experiment_name=None, run_name=None):
        self.manifest, self.out_dir = manifest, Path(out_dir)
        self.settings = manifest["config"]
        options = self.settings.get("experiment_tracking", {})
        self.uri = resolve_uri(tracking_uri or os.environ.get("MLFLOW_TRACKING_URI") or options.get("tracking_uri"))
        self.client = make_client(self.uri)
        name = experiment_name or options.get("experiment_name", "AskGov-supervisor")
        experiment = self.client.get_experiment_by_name(name)
        if experiment is None:
            # Explicit local artifacts keep storage out of whichever cwd launched Python.
            location = None
            if self.uri.startswith("sqlite:"):
                folder = PROJECT_ROOT / options.get("artifact_directory", "logs/mlflow/artifacts") / hashlib.sha256(name.encode()).hexdigest()[:12]
                folder.mkdir(parents=True, exist_ok=True)
                location = folder.resolve().as_uri()
            experiment_id = self.client.create_experiment(name, artifact_location=location)
        else:
            experiment_id = experiment.experiment_id
        parent = self.client.create_run(experiment_id, run_name=run_name or self.out_dir.name,
            tags={"kind": "evaluation_batch", "pipeline": manifest["pipeline"],
                  "question_set_sha256": manifest["question_set_sha256"]})
        self.parent_id = parent.info.run_id
        self.pending = set()
        self.metadata = {"tracking_uri": self.uri, "experiment_id": experiment_id,
                         "parent_run_id": self.parent_id, "children": {}}
        try:
            self.save_link()
            self.common = flatten(snapshot_settings(self.settings))
            self.common.update({"pipeline": manifest["pipeline"], "query_date": manifest["today"],
                "question_set_sha256": manifest["question_set_sha256"], "shuffle_seed": str(manifest["shuffle_seed"]),
                "source_data_sha256": json_hash(manifest["fingerprints"]),
                "config_sha256": json_hash(self.settings), "repeats": str(manifest["repeats"])})
            self.common.update({"git_commit": manifest.get("environment", {}).get("git_commit", "unknown"),
                                "git_dirty": str(manifest.get("environment", {}).get("git_dirty", True)).lower(),
                                "inference_callable": manifest.get("inference_callable", "unknown"),
                                "inference_is_injected": str(manifest.get("inference_is_injected", False)).lower()})
            log_values(self.client, self.parent_id, params=self.common)
            self.client.log_dict(self.parent_id, snapshot_settings(self.settings), "configuration.json")
            self.client.log_dict(self.parent_id, {**manifest, "config": snapshot_settings(self.settings)}, "manifest.json")
            self.client.log_dict(self.parent_id, manifest.get("environment", {}), "environment.json")
            # Preserve the exact prompt text as well as the fingerprints.
            for directory in ("agents/supervisor/prompts", "agents/graph/prompts", "agents/price/prompts"):
                self.client.log_artifacts(self.parent_id, str(PROJECT_ROOT / directory),
                                          artifact_path=directory)
        except BaseException:
            try:
                self.abort()
            except Exception:
                pass
            raise

    def save_link(self):
        (self.out_dir / "mlflow.json").write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    def begin_question(self, question, repeat, variant, review_id, decompose):
        child = self.client.create_run(self.metadata["experiment_id"],
            run_name=f"{question['question_id']} / {variant} / {repeat}",
            tags={"mlflow.parentRunId": self.parent_id, "kind": "question",
                  "variant": variant, "question_id": question["question_id"],
                  "category": question.get("category", "unspecified")})
        run_id = child.info.run_id
        self.pending.add(run_id)
        self.metadata["children"][review_id] = run_id
        self.save_link()
        params = {**self.common, **effective_params(self.settings, self.manifest["pipeline"], decompose),
                  "variant": variant, "question_id": question["question_id"], "repeat": str(repeat)}
        log_values(self.client, run_id, params=params)
        return run_id

    def complete_question(self, run_id, record):
        bundle = record.get("bundle", {})
        metrics = {key: record.get(key) for key in ("seconds", "input_tokens", "output_tokens", "model_calls", "cost_usd")}
        metrics.update(record.get("compute", {}))
        metrics.update(pipeline_error=int(bool(record.get("error"))),
            agent_error=int(bool(bundle.get("agent_errors"))),
            weak_self_check=int(bundle.get("self_check", {}).get("verdict") == "weak"),
            usage_incomplete=int(record.get("usage_incomplete", False)), retries=bundle.get("attempts", 0))
        pricing = self.settings.get("llm", {}).get("pricing", {})
        pricing_known = all(isinstance(pricing.get(k), (int, float))
                            and not isinstance(pricing.get(k), bool)
                            and math.isfinite(pricing[k]) and pricing[k] >= 0
                            for k in ("input_per_1m", "output_per_1m"))
        for u in bundle.get("usage", record.get("partial_usage", [])):
            prefix = "stage." + re.sub(r"[^a-zA-Z0-9_.-]", "_", u.get("step", "unknown"))
            for key in ("input_tokens", "output_tokens"):
                if u.get(key) is not None:
                    metrics[prefix + "." + key] = metrics.get(prefix + "." + key, 0) + u[key]
            metrics[prefix + ".calls"] = metrics.get(prefix + ".calls", 0) + u.get("calls", 1)
            if pricing_known and u.get("input_tokens") is not None and u.get("output_tokens") is not None:
                cost = (u["input_tokens"] * pricing.get("input_per_1m", 0) +
                        u["output_tokens"] * pricing.get("output_per_1m", 0)) / 1_000_000
                metrics[prefix + ".cost_usd"] = metrics.get(prefix + ".cost_usd", 0) + cost
        log_values(self.client, run_id, metrics=metrics)
        self.client.log_dict(run_id, record, "result.json")
        self.client.set_terminated(run_id, status="FAILED" if record.get("error") else "FINISHED")
        self.pending.discard(run_id)

    def finish(self, summaries):
        for summary in summaries:
            if summary["group"] == "all":
                log_values(self.client, self.parent_id, metrics={summary["variant"] + "." + key: value
                    for key, value in summary.items() if key not in ("variant", "group")})
        for name in ("manifest.json", "runs.jsonl", "efficiency.json", "grading_blind.csv", "review_key.csv", "comparison.csv", "experiment.xlsx"):
            if (self.out_dir / name).exists():
                if name == "manifest.json":
                    self.client.log_dict(self.parent_id, {**self.manifest,
                        "config": snapshot_settings(self.settings)}, name)
                else:
                    self.client.log_artifact(self.parent_id, str(self.out_dir / name))
        self.client.set_terminated(self.parent_id, status="FINISHED")
        self.save_link()

    def abort(self):
        for run_id in self.pending | {self.parent_id}:
            self.client.set_terminated(run_id, status="FAILED")


def publish_grades(run_dir, grading_path, scores):
    """Attach independently reviewed grades to the already executed runs."""
    import csv
    run_dir = Path(run_dir)
    link = json.loads((run_dir / "mlflow.json").read_text())
    client = make_client(os.environ.get("MLFLOW_TRACKING_URI") or link["tracking_uri"])
    with open(grading_path, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        child_id = link["children"][row["review_id"]]
        log_values(client, child_id, metrics={"quality." + key: float(row[key]) for key in
            ("correctness", "completeness", "groundedness", "appropriate_abstention")})
    parent_metrics = {f"{q['variant']}.quality.{q['metric']}": q["mean"]
                      for q in scores["quality"] if q["group"] == "all"}
    parent_metrics.update({"paired_B_minus_A." + key: value["mean"]
                          for key, value in scores["paired_B_minus_A"].items()})
    log_values(client, link["parent_run_id"], metrics=parent_metrics)
    client.log_dict(link["parent_run_id"], scores, "quality_scores.json")
    client.log_artifact(link["parent_run_id"], str(grading_path), artifact_path="grading")
    client.log_artifact(link["parent_run_id"], str(run_dir / "comparison.csv"))
    if (run_dir / "experiment.xlsx").exists():
        client.log_artifact(link["parent_run_id"], str(run_dir / "experiment.xlsx"))
    return link
