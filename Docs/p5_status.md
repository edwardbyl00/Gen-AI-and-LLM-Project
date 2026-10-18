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


## Latest main integration — 18 Oct 2026

### Real P4 corpus compatibility
- P5 successfully loads and retrieves from P4's real processed corpus.
- Real corpus size: 587 chunks.
- `test_data_integration.py` passes against the real corpus.
- P5's existing chunk adapter is compatible with P4's current chunk schema.

### Effective-date readiness
Real-corpus date audit:

- Total chunks: 587
- With `effective_date`: 0
- Missing `effective_date`: 587
- Date coverage: 0.0%

Missing by source:
- HDB: 352
- CPF: 57
- SSO: 145
- IRAS: 33

Therefore, date-aware retrieval is implemented and tested with mock data, but cannot yet be validated on the real corpus. Missing dates must not be inferred.

### Dense retrieval integration
P5 already supports hybrid BM25 + dense retrieval through RRF.

The current real P4 corpus is available, but a production-ready dense/vector retrieval interface has not yet been integrated into P5. Once P4 exposes the final semantic retriever, P5 will connect it to the existing hybrid retrieval path.

### Shared configuration
- LLM judge model is now read from `config.yaml`.
- Current judge model: `gpt-5.4`.
- P5 dependencies have been added to the shared `requirements.txt`.

## Testing

Run all free regression tests:

```powershell
py tests/run_all.py