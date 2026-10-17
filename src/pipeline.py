from policy_retriever import retrieve_policy_evidence
from llm_judge import judge_answer


def evaluate_answer(
    question,
    answer,
    query_date=None,
    top_k=3,
    policies=None
):
    """
    Retrieve evidence and judge an answer against that evidence.
    """

    retrieval = retrieve_policy_evidence(
        question=question,
        query_date=query_date,
        top_k=top_k,
        policies=policies
    )

    judgement = judge_answer(
        question=question,
        answer=answer,
        evidence=retrieval["evidence"]
    )

    return {
        "retrieval": retrieval,
        "judgement": judgement
    }


if __name__ == "__main__":
    result = evaluate_answer(
        question="Can I use OA savings for my flat?",
        answer=(
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
        query_date="2026-06-01"
    )

    print("\nRetrieved evidence:")
    for item in result["retrieval"]["evidence"]:
        print(
            item["document_id"],
            "|",
            item["title"]
        )

    print("\nJudge:")
    print(result["judgement"]["judgement"])

    print("\nUsage:")
    print(result["judgement"]["usage"])