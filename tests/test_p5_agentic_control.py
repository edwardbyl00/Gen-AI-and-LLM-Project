import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _retrieval(evidence, query="test query"):
    return {
        "question": query,
        "query_date": None,
        "final_query": query,
        "requeried": False,
        "rewrite_accepted": False,
        "retrieval_mode": "mock",
        "top_score": 1.0,
        "coverage": 1.0,
        "top_dense_score": None,
        "evidence": evidence,
    }


def _evidence(chunk_id, text):
    return {
        "chunk_id": chunk_id,
        "document_id": chunk_id.split("_")[0],
        "title": "Test policy",
        "source": "HDB",
        "url": "https://example.com",
        "effective_date": None,
        "text": text,
        "score": 1.0,
    }


def test_agent_self_corrects_after_decomposition(
    monkeypatch,
):
    import policy_agent

    initial = _evidence(
        "A_c0001",
        "General housing information.",
    )

    recovered = _evidence(
        "B_c0001",
        "Direct policy evidence needed to answer.",
    )

    retrieval_calls = []

    def fake_retrieve(
        question,
        query_date=None,
        top_k=3,
        policies=None,
        dense_results=None,
        use_dense=False,
    ):
        retrieval_calls.append(question)

        if question == "original question":
            return _retrieval(
                [initial],
                question,
            )

        return _retrieval(
            [recovered],
            question,
        )

    assessments = [
        {
            "sufficient": False,
            "answer_mode": "direct",
            "reason": "Key policy rule is missing.",
            "relevant_indices": [1],
            "missing_policy_information": (
                "Need the specific eligibility rule."
            ),
            "missing_user_information": [],
            "suggested_queries": [
                "site:hdb.gov.sg specific eligibility rule"
            ],
        },
        {
            "sufficient": True,
            "answer_mode": "direct",
            "reason": "Recovered evidence is sufficient.",
            "relevant_indices": [2],
            "missing_policy_information": "",
            "missing_user_information": [],
            "suggested_queries": [],
        },
    ]

    def fake_assessor(question, evidence):
        return assessments.pop(0)

    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        fake_retrieve,
    )

    result = policy_agent.run_policy_agent(
        "original question",
        top_k=10,
        use_dense=True,
        use_llm_assessor=True,
        assessor_fn=fake_assessor,
    )

    assert result["decision"] == "ANSWER_READY"

    assert [item["chunk_id"] for item in result["retrieval"]["retrieved_evidence"]] == [
        "A_c0001", "B_c0001"]

    assert [
        item["chunk_id"]
        for item in result["retrieval"]["evidence"]
    ] == ["B_c0001"]

    steps = [
        item["step"]
        for item in result["trace"]
    ]

    assert "ASSESS_EVIDENCE" in steps
    assert "DECOMPOSE_QUERY" in steps
    assert "REASSESS_EVIDENCE" in steps
    assert "ANSWER_READY" in steps

    # Confirms web-search syntax was cleaned before
    # querying the local corpus.
    assert any(
        query == "specific eligibility rule"
        for query in retrieval_calls
    )


def test_agent_abstains_when_self_correction_fails(
    monkeypatch,
):
    import policy_agent

    initial = _evidence(
        "A_c0001",
        "Only loosely related information.",
    )

    extra = _evidence(
        "B_c0001",
        "Still does not contain the required rule.",
    )

    def fake_retrieve(
        question,
        query_date=None,
        top_k=3,
        policies=None,
        dense_results=None,
        use_dense=False,
    ):
        if question == "unsupported question":
            return _retrieval(
                [initial],
                question,
            )

        return _retrieval(
            [extra],
            question,
        )

    assessments = [
        {
            "sufficient": False,
            "answer_mode": "direct",
            "reason": "Evidence is insufficient.",
            "relevant_indices": [],
            "missing_policy_information": (
                "Required policy rule is absent."
            ),
            "missing_user_information": [],
            "suggested_queries": [
                "target missing policy rule"
            ],
        },
        {
            "sufficient": False,
            "answer_mode": "direct",
            "reason": (
                "Evidence remains insufficient "
                "after targeted retrieval."
            ),
            "relevant_indices": [],
            "missing_policy_information": (
                "Required policy rule is still absent."
            ),
            "missing_user_information": [],
            "suggested_queries": [],
        },
    ]

    def fake_assessor(question, evidence):
        return assessments.pop(0)

    monkeypatch.setattr(
        policy_agent,
        "retrieve_policy_evidence",
        fake_retrieve,
    )

    result = policy_agent.run_policy_agent(
        "unsupported question",
        top_k=10,
        use_dense=True,
        use_llm_assessor=True,
        assessor_fn=fake_assessor,
    )

    assert result["decision"] == "ABSTAIN"

    assert result["retrieval"]["evidence"] == []
    assert [item["chunk_id"] for item in result["retrieval"]["retrieved_evidence"]] == [
        "A_c0001", "B_c0001"]

    steps = [
        item["step"]
        for item in result["trace"]
    ]

    assert "ASSESS_EVIDENCE" in steps
    assert "DECOMPOSE_QUERY" in steps
    assert "REASSESS_EVIDENCE" in steps
    assert steps[-1] == "ABSTAIN"
