# P5 – Advanced RAG / Policy Agent Status

## Scope

P5 implements advanced policy retrieval and evaluation for the housing-policy assistant.

Current components:

- Date-aware policy filtering
- Latest applicable policy-version selection
- BM25 keyword retrieval
- Query rewriting and re-query
- Retrieval evidence coverage checks
- Abstention when retrieved evidence is insufficient
- Reciprocal Rank Fusion (RRF)
- Hybrid BM25 + dense/vector retrieval interface
- Policy-agent decision trace
- AI-as-judge evaluation
- Token and estimated API-cost tracking
- P4 chunk-schema adapter
- End-to-end P5 evaluation pipeline

## Main Flow

Question

→ BM25 retrieval

→ optional query rewrite / re-query

→ optional dense/vector retrieval

→ Reciprocal Rank Fusion

→ evidence validation

→ ANSWER_READY or ABSTAIN

→ candidate answer

→ AI judge

## Main Source Files

- `src/retrieval.py`
  - BM25
  - query coverage
  - query rewriting
  - re-query logic

- `src/date_utils.py`
  - effective-date filtering
  - latest-version selection
  - date metadata audit

- `src/hybrid_retriever.py`
  - Reciprocal Rank Fusion
  - hybrid retrieval wrapper

- `src/policy_retriever.py`
  - retrieval interface
  - evidence packaging

- `src/policy_agent.py`
  - policy-agent decision logic
  - evidence validation
  - abstention
  - execution trace

- `src/llm_judge.py`
  - evaluation rubric
  - prompt construction
  - judge-output validation
  - OpenAI judge
  - token/cost tracking

- `src/chunk_adapter.py`
  - P4 chunk-schema normalisation

- `src/pipeline.py`
  - end-to-end P5 evaluation pipeline

## Testing

Run all free regression tests:

```powershell
py tests/run_all.py