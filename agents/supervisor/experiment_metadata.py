"""Local experiment configuration and provenance; no tracking service."""

import hashlib
import importlib.metadata
import json
import subprocess

from agents.supervisor.router import PROJECT_ROOT


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
