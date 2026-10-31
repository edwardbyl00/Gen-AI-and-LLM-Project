from policy_retriever import retrieve_policy_evidence


def _add_assessor_usage(total, assessment):
    """Accumulate token usage and latency from one assessor call."""
    total["calls"] += 1

    usage = assessment.get("_usage", {})

    total["input_tokens"] += int(
        usage.get("input_tokens", 0)
    )
    total["output_tokens"] += int(
        usage.get("output_tokens", 0)
    )
    total["total_tokens"] += int(
        usage.get("total_tokens", 0)
    )
    total["latency_seconds"] += float(
        usage.get("latency_seconds", 0.0)
    )


def _format_assessor_usage(total):
    """Return assessor usage with stable, rounded output."""
    return {
        **total,
        "latency_seconds": round(
            total["latency_seconds"],
            3,
        ),
    }


def _clean_requery(query):
    query = str(query or "").strip()

    removable = [
        "site:www.hdb.gov.sg",
        "site:www.cpf.gov.sg",
        "site:hdb.gov.sg",
        "site:cpf.gov.sg",
        "www.hdb.gov.sg",
        "www.cpf.gov.sg",
        "hdb.gov.sg",
        "cpf.gov.sg",
    ]

    lower_query = query.lower()

    for token in removable:
        lower_query = lower_query.replace(
            token,
            "",
        )

    return " ".join(
        lower_query.split()
    )


def _merge_evidence(*evidence_lists):
    """Combine evidence lists without duplicate chunks."""
    merged = []
    seen = set()

    for evidence in evidence_lists:
        for item in evidence:
            key = (
                item.get("chunk_id")
                or item.get("document_id")
            )

            if key in seen:
                continue

            seen.add(key)
            merged.append(item)

    return merged


def run_policy_agent(
    question,
    query_date=None,
    top_k=3,
    policies=None,
    dense_results=None,
    use_dense=False,
    use_llm_assessor=False,
    assessor_fn=None,
):
    """
    Agentic policy retrieval loop.

    Steps:
    1. Retrieve policy evidence.
    2. Re-query automatically if retrieval is weak.
    3. Check whether usable evidence remains.
    4. Optionally use an LLM assessor and one self-correction loop.
    5. Decide whether the system is ready to answer or should abstain.
    """
    assessor_usage = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "latency_seconds": 0.0,
    }

    trace = []

    # Step 1: Retrieve
    trace.append({
        "step": "RETRIEVE",
        "query": question,
    })

    retrieval = retrieve_policy_evidence(
        question,
        query_date=query_date,
        top_k=top_k,
        policies=policies,
        dense_results=dense_results,
        use_dense=use_dense,
    )

    # Step 2: Record re-query if it happened
    if retrieval.get("requeried"):
        trace.append({
            "step": "REQUERY",
            "query": retrieval.get("final_query"),
            "accepted": retrieval.get("rewrite_accepted"),
        })

    evidence = retrieval.get("evidence", [])
    # Preserve candidates for offline diagnosis even when the evidence gate
    # later removes them from the passages supplied to synthesis.
    retrieval["retrieved_evidence"] = list(evidence)

    # Step 3: Stop immediately when retrieval found no evidence.
    if not evidence:
        reason = "No relevant policy evidence was retrieved."

        trace.append({
            "step": "CHECK_EVIDENCE",
            "result": "NO_EVIDENCE",
        })

        trace.append({
            "step": "ABSTAIN",
            "reason": reason,
        })

        return {
            "decision": "ABSTAIN",
            "reason": reason,
            "retrieval": retrieval,
            "trace": trace,
            "assessor_usage": _format_assessor_usage(
                assessor_usage
            ),
        }

    # --------------------------------------------------
    # LLM evidence assessment + one self-correction loop
    # --------------------------------------------------
    if use_llm_assessor:
        if assessor_fn is None:
            from evidence_assessor import assess_evidence
            assessor_fn = assess_evidence

        first_assessment = assessor_fn(
            question,
            evidence,
        )

        _add_assessor_usage(
            assessor_usage,
            first_assessment,
        )

        trace.append({
            "step": "ASSESS_EVIDENCE",
            "sufficient": first_assessment["sufficient"],
            "answer_mode": first_assessment.get(
                "answer_mode"
            ),
            "reason": first_assessment["reason"],
            "relevant_indices": first_assessment[
                "relevant_indices"
            ],
            "missing_user_information": first_assessment.get(
                "missing_user_information",
                [],
            ),
        })

        # Evidence already sufficient.
        if first_assessment["sufficient"]:
            selected = [
                evidence[index - 1]
                for index in first_assessment[
                    "relevant_indices"
                ]
                if 1 <= index <= len(evidence)
            ]

            if selected:
                retrieval["evidence"] = selected

            trace.append({
                "step": "ANSWER_READY",
            })

            return {
                "decision": "ANSWER_READY",
                "reason": first_assessment["reason"],
                "retrieval": retrieval,
                "trace": trace,
                "assessor_usage": _format_assessor_usage(
                    assessor_usage
                ),
            }

        # --------------------------------------------------
        # Self-correction: targeted subqueries
        # --------------------------------------------------
        suggested_queries = first_assessment.get(
            "suggested_queries",
            [],
        )

        if suggested_queries:
            cleaned_queries = []

            for subquery in suggested_queries:
                cleaned = _clean_requery(subquery)

                if cleaned:
                    cleaned_queries.append(cleaned)

            trace.append({
                "step": "DECOMPOSE_QUERY",
                "queries": cleaned_queries,
            })

            extra_evidence = []

            for subquery in cleaned_queries:
                sub_retrieval = retrieve_policy_evidence(
                    subquery,
                    query_date=query_date,
                    top_k=10,
                    policies=policies,
                    use_dense=use_dense,
                )

                extra_evidence.extend(
                    sub_retrieval.get(
                        "evidence",
                        [],
                    )
                )

            combined_evidence = _merge_evidence(
                evidence,
                extra_evidence,
            )
            retrieval["retrieved_evidence"] = list(combined_evidence)

            second_assessment = assessor_fn(
                question,
                combined_evidence,
            )

            _add_assessor_usage(
                assessor_usage,
                second_assessment,
            )

            trace.append({
                "step": "REASSESS_EVIDENCE",
                "sufficient": second_assessment["sufficient"],
                "answer_mode": second_assessment.get(
                    "answer_mode"
                ),
                "reason": second_assessment["reason"],
                "relevant_indices": second_assessment[
                    "relevant_indices"
                ],
                "missing_user_information": second_assessment.get(
                    "missing_user_information",
                    [],
                ),
            })

            if second_assessment["sufficient"]:
                selected = [
                    combined_evidence[index - 1]
                    for index in second_assessment[
                        "relevant_indices"
                    ]
                    if 1 <= index <= len(
                        combined_evidence
                    )
                ]

                retrieval["evidence"] = selected

                trace.append({
                    "step": "ANSWER_READY",
                })

                return {
                    "decision": "ANSWER_READY",
                    "reason": second_assessment["reason"],
                    "retrieval": retrieval,
                    "trace": trace,
                    "assessor_usage": _format_assessor_usage(
                        assessor_usage
                    ),
                }

        # Still insufficient after self-correction, or no useful
        # suggested queries were produced.
        retrieval["evidence"] = []

        trace.append({
            "step": "ABSTAIN",
            "reason": first_assessment["reason"],
        })

        return {
            "decision": "ABSTAIN",
            "reason": first_assessment["reason"],
            "retrieval": retrieval,
            "trace": trace,
            "assessor_usage": _format_assessor_usage(
                assessor_usage
            ),
        }

    # --------------------------------------------------
    # Legacy deterministic evidence gate
    # --------------------------------------------------
    top_score = evidence[0].get("score", 0)
    coverage = retrieval.get("final_coverage", 0.0)
    top_dense_score = retrieval.get("top_dense_score")

    insufficient_dense = (
        retrieval.get("retrieval_mode") == "hybrid"
        and top_dense_score is not None
        and top_dense_score < 0.72
    )

    if top_score <= 0 or coverage < 0.5 or insufficient_dense:
        reason = "Retrieved evidence was not sufficiently relevant."

        trace.append({
            "step": "CHECK_EVIDENCE",
            "result": "INSUFFICIENT_EVIDENCE",
            "top_score": top_score,
            "top_dense_score": top_dense_score,
            "coverage": coverage,
        })

        trace.append({
            "step": "ABSTAIN",
            "reason": reason,
        })

        return {
            "decision": "ABSTAIN",
            "reason": reason,
            "retrieval": retrieval,
            "trace": trace,
            "assessor_usage": _format_assessor_usage(
                assessor_usage
            ),
        }

    # Evidence is usable.
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
        "assessor_usage": _format_assessor_usage(
            assessor_usage
        ),
    }
