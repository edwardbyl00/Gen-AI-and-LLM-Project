# Policy agent — Agentic RAG

## Status

This guide records the P5 implementation and its historical evaluation
checkpoint, with current supervisor integration notes checked on 31 October
2026. The pilot scores below are saved development results, not a benchmark
of the latest supervisor prompts or the new question-list evaluation.

The final P5 contribution extends the policy RAG pipeline with evidence assessment, targeted self-correction, reassessment, safe abstention, supervisor integration, regression tests, and efficiency telemetry.

The main finding is that naive hybrid retrieval did **not** consistently outperform the dense baseline. The strongest P5 value came from the agentic control loop:

**retrieve → assess evidence → targeted decomposition/self-correction → reassess → answer or abstain**

## Implemented Components

### Date-aware filtering
Date filtering utilities were implemented in `src/date_utils.py`.

Real-corpus validation was not possible because all **1,282 chunks** lacked authoritative policy `effective_date` metadata:

- HDB: 702 missing
- CPF: 303 missing
- SSO: 189 missing
- IRAS: 88 missing
- Date coverage: 0%

All chunks have `retrieved_at`, but this represents corpus capture time rather than policy effective date and was not used as a substitute.

### Advanced retrieval
P5 implemented BM25, BGE dense retrieval, Reciprocal Rank Fusion, query coverage checks, acronym-aware query rewriting, re-query support, and weighted hybrid experiments.

| Metric | Dense | Hybrid | Change |
|---|---:|---:|---:|
| Hit@5 | 0.667 | 0.641 | -0.026 |
| Hit@10 | 0.744 | 0.744 | 0.000 |
| Recall@5 | 0.363 | 0.341 | -0.021 |
| Recall@10 | 0.467 | 0.427 | -0.040 |
| MRR@10 | 0.473 | 0.477 | +0.004 |

Dense retrieval was the stronger experimental baseline on these metrics.
The current supervisor's real policy adapter calls the hybrid retrieval path
with dense retrieval and the LLM assessor enabled; the historical comparison
does not mean the live adapter runs dense-only retrieval.

### Evidence assessment and self-correction
`src/evidence_assessor.py` evaluates whether retrieved evidence is sufficient for a grounded answer. It distinguishes missing policy evidence from missing user-specific information, allowing conditional answers when the policy evidence is adequate.

`src/policy_agent.py` then:
1. retrieves evidence;
2. assesses sufficiency;
3. answers immediately if sufficient;
4. otherwise generates up to two targeted local-corpus queries;
5. retrieves and merges additional evidence;
6. reassesses against the original question; and
7. returns `ANSWER_READY` or `ABSTAIN`.

Web-specific syntax such as `site:hdb.gov.sg` and `site:cpf.gov.sg` is removed before local retrieval.

### Safe abstention
If no usable evidence is retrieved, or evidence remains insufficient after self-correction, the agent returns `ABSTAIN` instead of allowing unsupported policy claims.

The assessor judges supplied candidates, not the full corpus. An `ABSTAIN`
therefore does not prove that supporting evidence does not exist elsewhere.
`retrieved_evidence` now preserves candidates even when selected `evidence`
is cleared, allowing offline review to separate corpus gaps, retrieval misses
and evidence-selection issues. Policy decisions/reasons are also saved in
the shared steps and [CSV usage logs](usage_logging.md).

### Supervisor integration
P5 is integrated through `agents/supervisor/adapters.py` with configuration-driven retrieval limits. P1 price functionality remains outside P5 scope.

### Automated testing
The final regression suite includes original P5 tests, supervisor tests, P5 integration tests, and deterministic agentic-control tests.

`tests/test_p5_agentic_control.py` validates:
- successful self-correction after decomposition;
- safe abstention when self-correction still fails.

`tests/test_p5_integration.py` validates:
- local query cleaning;
- configuration-driven `top_k`;
- forwarding of LLM-assessor settings.

All tests passed at the final implementation checkpoint.

## Evaluation

### Dense baseline
The dense baseline uses `BAAI/bge-base-en-v1.5`, cosine similarity, and a 1,282-chunk corpus.

| Metric | Score |
|---|---:|
| Hit@5 | 0.667 |
| Hit@10 | 0.744 |
| Recall@5 | 0.363 |
| Recall@10 | 0.467 |
| MRR@10 | 0.473 |

### Final 10-question baseline vs agentic pilot

Pilot IDs: `H01, H07, H14, H15, H23, H29, C01, C04, C06, C10`

#### Answer quality

| Metric | Baseline | Agentic |
|---|---:|---:|
| Faithfulness-style LLM judge | 7.6 / 10 | 8.4 / 10 |
| Ground-truth LLM judge | 6.9 / 10 | 8.6 / 10 |

Agentic decisions:
- `ANSWER_READY`: 8 / 10
- `ABSTAIN`: 2 / 10

#### Efficiency trade-off

| Metric | Result |
|---|---:|
| Baseline mean latency | 6.504 s/question |
| Agentic mean latency | 14.294 s/question |
| Agentic latency overhead | +7.790 s/question |
| Evidence-assessor calls | 15 total |
| Average assessor calls | 1.5/question |
| Assessor tokens | 60,052 total |
| Average assessor tokens | 6,005.2/question |
| Average assessor latency | 6.073 s/question |

The pilot's model-judge scores were higher on both lenses, with additional
LLM calls, tokens and latency. These are unvalidated judge observations, not
independently established correctness or a current system-wide improvement;
see [judge validation](llm_judge_validation.md) and [stage review](stage_evaluation.md).

The reported **USD 0.1776** is the cost of the LLM-as-judge evaluation calls only and should not be interpreted as the full production cost of the agentic pipeline.

### Repeatability
Across three repeated runs of the 10-question pilot:
- mean decision agreement: 96.7%;
- 9/10 questions were fully stable;
- H01 was the only borderline case with decision variation.

### Key examples
**C06** is the clearest self-correction example: initial evidence was insufficient, targeted decomposition retrieved additional evidence, reassessment succeeded, and the case became `ANSWER_READY`.

**H29** is an evidence-gap control asking for resale-price aggregation. The policy corpus does not contain the required transaction data, so it should not be treated as an ordinary policy-RAG failure.

## Overall P5 Finding

Naive hybrid retrieval did not outperform the dense baseline consistently. The main P5 improvement came from the agentic control loop:

**retrieve → assess → self-correct/decompose → reassess → answer or abstain**

The historical pilot suggests a benefit on its model-judge measures while
providing an explicit insufficient-evidence decision. The observed trade-off
was higher latency and token usage; independent review is still needed.

## Limitations

- Hybrid retrieval did not improve aggregate retrieval performance.
- All 1,282 chunks lacked authoritative policy effective-date metadata.
- H01 remained a stochastic borderline case.
- H29 is outside the policy corpus and belongs to the price-agent route.
- Agentic evidence assessment increases latency and token usage.
- The answer-quality pilot uses 10 questions, while retrieval evaluation covers 39 ordinary policy questions.
- P1 price-agent implementation is outside P5 scope.

## Reproducibility

Run the full regression suite:

```powershell
python tests/run_all.py
```

Run the final judged baseline-vs-agentic pilot:

```powershell
$env:PYTHONPATH=".;src"
python scripts/evaluate_agentic_answers.py --judge
```

Key outputs:

- `evaluation/retrieval/advanced_retrieval_metrics.json`
- `evaluation/retrieval/advanced_retrieval_results_40q.csv`
- `evaluation/agentic/agentic_vs_baseline_pilot_10q_judged.json`
- `evaluation/agentic/agentic_vs_baseline_pilot_10q_judged_efficiency_summary.json`
