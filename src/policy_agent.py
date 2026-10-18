from policy_retriever import retrieve_policy_evidence


def run_policy_agent(
    question,
    query_date=None,
    top_k=3,
    policies=None,
):
    """
    Agentic policy retrieval loop.

    Steps:
    1. Retrieve policy evidence.
    2. Re-query automatically if retrieval is weak.
    3. Check whether usable evidence remains.
    4. Decide whether the system is ready to answer
       or should abstain.
    """

    trace = []

    # Step 1: Retrieve
    trace.append({
        "step": "RETRIEVE",
        "query": question,
    })

    retrieval = retrieve_policy_evidence(
        question=question,
        query_date=query_date,
        top_k=top_k,
        policies=policies,
    )

    # Step 2: Record re-query if it happened
    if retrieval.get("requeried"):
        trace.append({
            "step": "REQUERY",
            "query": retrieval.get("final_query"),
            "accepted": retrieval.get("rewrite_accepted"),
        })

    evidence = retrieval.get("evidence", [])

    # Step 3: Evidence check
    if not evidence:
        trace.append({
            "step": "CHECK_EVIDENCE",
            "result": "NO_EVIDENCE",
        })

        trace.append({
            "step": "ABSTAIN",
            "reason": "No relevant policy evidence was retrieved.",
        })

        return {
            "decision": "ABSTAIN",
            "reason": "No relevant policy evidence was retrieved.",
            "retrieval": retrieval,
            "trace": trace,
        }

    top_score = evidence[0].get("score", 0)
    coverage = retrieval.get("final_coverage", 0.0)

    if top_score <= 0 or coverage < 0.5:
        trace.append({
            "step": "CHECK_EVIDENCE",
            "result": "INSUFFICIENT_EVIDENCE",
            "top_score": top_score,
            "coverage": coverage,
        })

        trace.append({
            "step": "ABSTAIN",
            "reason": "Retrieved evidence was not sufficiently relevant.",
        })

        return {
            "decision": "ABSTAIN",
            "reason": "Retrieved evidence was not sufficiently relevant.",
            "retrieval": retrieval,
            "trace": trace,
        }

    # Evidence is usable
    trace.append({
        "step": "CHECK_EVIDENCE",
        "result": "EVIDENCE_FOUND",
        "top_score": top_score,
        "coverage": coverage,
    })

    trace.append({
        "step": "ANSWER_READY",
    })

    return {
        "decision": "ANSWER_READY",
        "reason": "Relevant policy evidence was retrieved.",
        "retrieval": retrieval,
        "trace": trace,
    }