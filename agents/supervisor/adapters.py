"""Adapters between the supervisor and the price and policy agents.

Each adapter returns the shape pipeline.py and synthesis.py expect (see
Docs/p2_supervisor_code.md). If an agent's own output changes, only its
adapter changes.

The price agent is always real now; there's no price stub. The policy
agent can still be run as a stub (set agents.policy to "stub" in
config.yaml) -- it returns fake data, clearly marked, so the pipeline can
be built, tested, or run without the real policy dependencies.
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

def price_real(question, query_date):
    """Call P1's real price agent using the approach selected in config.yaml."""
    # Lazy import keeps stub mode usable without price dependencies or data.
    from agents.price import run_price_agent

    return run_price_agent(question, query_date)


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
    """Call P5's agentic policy agent: hybrid (BM25 + dense) retrieval, an
    automatic re-query, then an LLM evidence check with one self-correction
    pass before deciding whether there's enough to answer from."""
    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        # P5's modules import each other by bare name (e.g. hybrid_search),
        # so src/ must be on the import path.
        sys.path.insert(0, src)
    try:
        # Import only when the real agent is called, so stub mode can run
        # without P5's code or its dependencies (rank-bm25, chromadb,
        # torch, transformers) installed.
        from policy_agent import run_policy_agent
    except ImportError as error:
        raise ImportError(
            "Could not import P5's policy agent (src/policy_agent.py). "
            "Check that its dependencies are installed (pip install -r "
            "requirements.txt), or set agents.policy to 'stub'."
        ) from error

    agent_result = run_policy_agent(
        question, query_date=query_date, top_k=top_k,
        use_dense=True, use_llm_assessor=True,
    )

    # Keep the pipeline's expected top-level shape (an "evidence" key),
    # with the agent's own decision/reason/trace alongside it for the step
    # log, rather than nested under a separate "retrieval" key.
    result = dict(agent_result.get("retrieval", {}))
    result["decision"] = agent_result.get("decision")
    result["reason"] = agent_result.get("reason")
    result["trace"] = agent_result.get("trace", [])

    # If the agent decided the evidence was too weak, don't let synthesis
    # answer from it anyway -- treat it the same as "nothing retrieved".
    if result["decision"] != "ANSWER_READY":
        result["evidence"] = []

    # Synthesis needs url and effective_date on every item to cite sources.
    for item in result.get("evidence", []):
        item.setdefault("url", None)
        item.setdefault("effective_date", None)
    return result


# ---------- choose stub or real from config.yaml ----------

def get_price_agent(settings=None):
    """Return the price agent. There's no stub anymore, so this always
    returns price_real; settings is accepted only to keep the same call
    shape as get_policy_agent()."""
    return price_real


def get_policy_agent(settings=None):
    """Bind the configured retrieval limit to the pipeline's two-argument API."""
    settings = settings if settings is not None else load_agent_settings()
    top_k = settings.get("policy_top_k", 3)
    agent = policy_real if settings.get("policy") == "real" else policy_stub
    return lambda question, query_date: agent(question, query_date, top_k=top_k)
