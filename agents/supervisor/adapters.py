"""Adapters between the supervisor and the price and policy agents.

Each adapter returns the shape agreed in Docs/p2_supervisor_contract.md
(section A4). If an agent's own output changes, only its adapter changes.

Which version is used ("stub" or "real") is set in config.yaml under
"agents". Stubs return fake data, clearly marked, so the pipeline can be
built and tested before the real agents exist.
"""

import sys

import yaml

from agents.supervisor.router import CONFIG_FILE, PROJECT_ROOT


def load_agent_settings():
    """Read the "agents" section of config.yaml."""
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}
    return config.get("agents", {})


# ---------- price agent (P1) ----------

def price_stub(question, query_date):
    """Return fixed sample prices, regardless of the question, for local testing."""
    return {
        "town": "STUB", "flat_type": "STUB",
        "period_start": "2025-10", "period_end": "2026-09",
        "median_price": 500000, "min_price": 400000, "max_price": 600000,
        "n_deals": 100, "data_as_of": query_date,
        "stub": True,
    }


def price_real(question, query_date):
    """Call P1's price agent. Not available yet."""
    raise NotImplementedError(
        "P1's price agent is not in this branch yet. "
        "Set agents.price to 'stub' in config.yaml."
    )


# ---------- policy agent (P5, built on P4's index) ----------

def policy_stub(question, query_date, top_k=3):
    """Return one sample passage in P5's shape; top_k is ignored by this stub."""
    return {
        "question": question, "query_date": query_date,
        "final_query": question, "requeried": False, "rewrite_accepted": False,
        "evidence": [{
            "document_id": "STUB", "chunk_id": "STUB_c0001",
            "title": "Stub passage", "source": "STUB", "category": "STUB",
            "url": "https://example.invalid/stub", "effective_date": None,
            "text": "STUB passage: not real policy text.",
            "section_title": None, "section_path": None, "score": 0.0,
        }],
        "stub": True,
    }


def policy_real(question, query_date, top_k=3):
    """Call P5's policy agent with real hybrid retrieval."""
    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    try:
        from policy_agent import run_policy_agent
    except ImportError as error:
        raise ImportError(
            "P5's policy agent (src/policy_agent.py) is not available. "
            "Merge it, or set agents.policy to 'stub'."
        ) from error

    agent_result = run_policy_agent(
        question,
        query_date=query_date,
        top_k=top_k,
        use_dense=True,
    )

    retrieval = agent_result.get("retrieval", {})

    # Keep P2's expected top-level retrieval shape.
    result = dict(retrieval)

    # Add P5 agentic decision information.
    result["decision"] = agent_result.get("decision")
    result["reason"] = agent_result.get("reason")
    result["trace"] = agent_result.get("trace", [])

    # If P5 decides evidence is insufficient, do not let synthesis
    # answer from that weak evidence.
    if result["decision"] != "ANSWER_READY":
        result["evidence"] = []

    # Synthesis needs these fields for citations.
    for item in result.get("evidence", []):
        item.setdefault("url", None)
        item.setdefault("effective_date", None)

    return result


# ---------- choose stub or real from config.yaml ----------

def get_price_agent(settings=None):
    """Select the real price agent only when explicitly configured as 'real'."""
    # An explicitly supplied empty dict also selects defaults without reading disk.
    settings = settings if settings is not None else load_agent_settings()
    return price_real if settings.get("price") == "real" else price_stub


def get_policy_agent(settings=None):
    """Bind the configured retrieval limit to the pipeline's two-argument API."""
    settings = settings if settings is not None else load_agent_settings()
    top_k = settings.get("policy_top_k", 3)
    agent = policy_real if settings.get("policy") == "real" else policy_stub
    return lambda question, query_date: agent(question, query_date, top_k=top_k)
