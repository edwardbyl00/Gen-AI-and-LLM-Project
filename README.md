# AskGov SG — Gen AI and LLM Project

AskGov SG routes HDB/CPF housing questions to policy retrieval, resale-price analysis, or both, then synthesizes an answer with policy sources. Pricing always uses the real agent; policy is currently configured as real.

Start with the [end-to-end pipeline map](Docs/end_to_end_overview.md) for how the phases fit together, then the [P2 supervisor code guide](Docs/p2_supervisor_code.md) for the high-level flow, detailed decision branches, bundle, token/cost tracking and evaluation commands. See the [price-agent guide](agents/price/README.md) for P1 details and the [maintenance guide](Docs/MAINTENANCE.md) for team setup and Git conventions.

The supervisor uses v2 prompts: routing flags `check_premise`, while synthesis checks the claim against retrieved evidence. Saved evaluations live under `evaluation/results/` and `evaluation/answers/`.

Supervisor and P3 runs append local usage history to `logs/usage/runs.csv`
(one row per question) and `logs/usage/calls.csv` (stage/task breakdown).
Open these CSVs in Excel or another spreadsheet app. See the
[usage log guide](Docs/usage_logging.md) for columns and settings.

For parameter/configuration experiments, add `--mlflow` to the ablation runner.
It records effective A/B settings, model/retrieval/review parameters, API cost,
latency, local CPU/memory and later team grades in one UI. See the
[MLflow experiment guide](Docs/mlflow_experiments.md) for setup and comparison.

Router decomposition (on by default via `supervisor.decompose` in
`config.yaml`; pass `decompose=False` to run the plain baseline) and paired
A/B evaluation are described in the [supervisor ablation and unseen-question
guide](Docs/supervisor_ablation.md), including the team's input format,
blinded grading and cost/quality comparison. The P3 graph uses the same
decomposition setting; select `--pipeline graph` in the ablation runner to
include its self-check loop in the comparison.

This README also includes the reproducible setup for the final P5 Agentic RAG evaluation below.

## Environment

Activate the project virtual environment from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
```

API credentials are stored in a local `.env` file. Do not commit `.env`.

Runtime model and agent settings are stored in:

```text
config.yaml
```

## P5 Agentic RAG

The final P5 policy flow is:

```text
Question
  ↓
Policy retrieval
  ↓
Evidence assessment
  ↓
Sufficient?
  ├─ Yes → select relevant evidence → ANSWER_READY
  └─ No
       ↓
    targeted decomposition
       ↓
    retrieve additional evidence
       ↓
    merge + deduplicate
       ↓
    reassess
       ├─ sufficient → ANSWER_READY
       └─ insufficient → ABSTAIN
```

P5 includes:

- BGE dense retrieval
- BM25 lexical retrieval
- Reciprocal Rank Fusion experiments
- query coverage and re-query logic
- LLM-based evidence sufficiency assessment
- targeted decomposition/self-correction
- evidence reassessment
- safe abstention
- token and latency telemetry
- supervisor integration
- automated regression and integration tests

The main finding was that naive hybrid retrieval did not consistently outperform the dense baseline. The strongest improvement came from the agentic evidence-assessment and self-correction loop.

## Run the Regression Suite

```powershell
python tests/run_all.py
```

The consolidated suite covers:

- retrieval
- date utilities
- data integration
- policy agent
- P5 pipeline
- supervisor components
- P5 integration
- deterministic self-correction
- safe abstention

## Run the Final P5 Evaluation

From the repository root:

```powershell
$env:PYTHONPATH=".;src"
python scripts/evaluate_agentic_answers.py --judge
```

The evaluator compares a single-pass dense RAG baseline against the P5 agentic pipeline.

### Baseline
- dense retrieval;
- synthesis;
- no evidence-assessor gate;
- no targeted decomposition;
- no agentic pre-synthesis abstention.

### Agentic P5
- retrieve evidence;
- assess sufficiency;
- generate targeted subqueries when needed;
- retrieve and merge additional evidence;
- reassess;
- answer or abstain.

## Final P5 Results

| Metric | Baseline | Agentic |
|---|---:|---:|
| Faithfulness-style LLM judge | 7.6 / 10 | 8.4 / 10 |
| Ground-truth LLM judge | 6.9 / 10 | 8.6 / 10 |
| Mean end-to-end latency | 6.504 s | 14.294 s |

Additional agentic efficiency results:

- latency overhead: +7.790 s/question
- evidence-assessor calls: 15 total
- average assessor calls: 1.5/question
- assessor tokens: 60,052 total
- average assessor tokens: 6,005.2/question
- average assessor latency: 6.073 s/question
- final decisions: 8 `ANSWER_READY`, 2 `ABSTAIN`

The agentic system improved answer quality on both evaluation rubrics, at the cost of additional LLM calls, token usage, and latency.

The evaluation output labelled `Judge cost USD` refers only to LLM-as-judge evaluation calls and should not be interpreted as the full production cost of the agentic pipeline.

## Evaluation Outputs

Final answer evaluation:

```text
evaluation/agentic_vs_baseline_pilot_10q_judged.json
```

Efficiency summary:

```text
evaluation/agentic_vs_baseline_pilot_10q_judged_efficiency_summary.json
```

Advanced retrieval evaluation:

```text
evaluation/advanced_retrieval_metrics.json
evaluation/advanced_retrieval_results_40q.csv
```

Dense baseline evaluation:

```text
evaluation/dense_retrieval_metrics.json
evaluation/dense_retrieval_results_40q.csv
```

## Important P5 Notes

### Date metadata
Date-aware filtering was implemented, but all 1,282 corpus chunks lacked authoritative policy `effective_date` metadata.

The available `retrieved_at` value represents corpus capture time and was not substituted for policy effective date.

### Hybrid retrieval
Equal-weight BM25 + dense RRF did not improve aggregate retrieval performance over the dense baseline. This negative result was retained rather than hidden through post-hoc tuning.

### Repeatability
Across three repeated runs of the 10-question agentic pilot:

- mean decision agreement: 96.7%;
- 9/10 questions were fully stable;
- H01 was the only borderline case with decision variation.

### H29
H29 asks for resale transaction-price aggregation. The policy corpus does not contain the required transaction data.

In the integrated system this question belongs to the price-agent route rather than the policy RAG route.

## P5 Key Files

```text
src/date_utils.py
src/retrieval.py
src/dense_retriever.py
src/hybrid_retriever.py
src/policy_retriever.py
src/evidence_assessor.py
src/policy_agent.py
src/pipeline.py
scripts/evaluate_advanced_retrieval.py
scripts/evaluate_agentic_answers.py
scripts/evaluate_agent_repeatability.py
tests/test_p5_agentic_control.py
tests/test_p5_integration.py
tests/run_all.py
```

For the detailed P5 implementation and evaluation record, see:

```text
Docs/p5_status.md
```
