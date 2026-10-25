import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_clean_requery_removes_web_search_syntax():
    from policy_agent import _clean_requery

    query = (
        "site:hdb.gov.sg HDB New Flat Eligibility "
        "SC SPR Married Couple"
    )

    cleaned = _clean_requery(query)

    assert "site:" not in cleaned
    assert "hdb.gov.sg" not in cleaned

    assert cleaned == (
        "hdb new flat eligibility "
        "sc spr married couple"
    )


def test_clean_requery_removes_cpf_domain():
    from policy_agent import _clean_requery

    query = (
        "www.cpf.gov.sg CPF second property "
        "BRS FRS rules"
    )

    cleaned = _clean_requery(query)

    assert "cpf.gov.sg" not in cleaned
    assert cleaned == (
        "cpf second property brs frs rules"
    )


def test_policy_top_k_comes_from_config(monkeypatch):
    from agents.supervisor import adapters

    captured = {}

    def fake_policy_real(
        question,
        query_date,
        top_k=3,
    ):
        captured["question"] = question
        captured["query_date"] = query_date
        captured["top_k"] = top_k

        return {
            "evidence": [],
            "decision": "ABSTAIN",
        }

    monkeypatch.setattr(
        adapters,
        "policy_real",
        fake_policy_real,
    )

    policy_agent = adapters.get_policy_agent({
        "policy": "real",
        "policy_top_k": 10,
    })

    policy_agent(
        "test question",
        "2026-10-24",
    )

    assert captured["top_k"] == 10


# A test for src/pipeline.py (a separate LLM-judge evaluation harness) was
# intentionally left out here: that module wasn't part of this sync, since
# it's unrelated to the supervisor's policy agent integration.