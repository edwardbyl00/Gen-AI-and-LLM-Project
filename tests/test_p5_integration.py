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

def test_evaluation_pipeline_forwards_llm_assessor(
    monkeypatch,
):
    import pipeline

    captured = {}

    def fake_assessor(question, evidence):
        return {"sufficient": True}

    def fake_run_policy_agent(
        question,
        **kwargs,
    ):
        captured.update(kwargs)

        return {
            "decision": "ANSWER_READY",
            "reason": "Test",
            "retrieval": {
                "retrieval_mode": "mock",
                "evidence": [],
            },
            "trace": [],
        }

    def fake_judge_answer(
        question,
        answer,
        evidence,
    ):
        return {"total_score": 10}

    monkeypatch.setattr(
        pipeline,
        "run_policy_agent",
        fake_run_policy_agent,
    )

    monkeypatch.setattr(
        pipeline,
        "judge_answer",
        fake_judge_answer,
    )

    pipeline.evaluate_candidate_answer(
        "test question",
        "test answer",
        use_dense=True,
        use_llm_assessor=True,
        assessor_fn=fake_assessor,
    )

    assert captured["use_dense"] is True
    assert captured["use_llm_assessor"] is True
    assert captured["assessor_fn"] is fake_assessor