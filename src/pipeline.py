from policy_agent import run_policy_agent
from llm_judge import judge_answer


def evaluate_candidate_answer(
    question,
    answer,
    query_date=None,
    top_k=3,
    policies=None,
    dense_results=None,
    use_dense=False,
    use_llm_assessor=False,
    assessor_fn=None,
):
    """
    Run the full P5 evaluation pipeline:

    1. Policy agent retrieves and validates evidence.
    2. Agent decides ANSWER_READY or ABSTAIN.
    3. AI judge evaluates the candidate answer
       against the retrieved evidence.
    """

    agent_result = run_policy_agent(
        question,
        query_date=query_date,
        top_k=top_k,
        policies=policies,
        dense_results=dense_results,
        use_dense=use_dense,
        use_llm_assessor=use_llm_assessor,
        assessor_fn=assessor_fn,
    )

    evidence = agent_result[
        "retrieval"
    ]["evidence"]

    judgement = judge_answer(
        question=question,
        answer=answer,
        evidence=evidence,
    )

    return {
        "question": question,
        "answer": answer,
        "agent_decision": (
            agent_result["decision"]
        ),
        "agent_reason": (
            agent_result["reason"]
        ),
        "retrieval_mode": (
            agent_result["retrieval"][
                "retrieval_mode"
            ]
        ),
        "evidence": evidence,
        "trace": agent_result["trace"],
        "judge": judgement,
    }