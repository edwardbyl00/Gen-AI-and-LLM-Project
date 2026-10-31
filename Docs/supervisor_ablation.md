# Supervisor decomposition ablation and unseen-question evaluation

This experiment compares A (decomposition disabled) with B (decomposition
enabled). Choose one execution path for both variants: `--pipeline supervisor`
(the default) runs routing, selected agents and synthesis; `--pipeline graph`
also includes P3's parallel agent branches and bounded self-check loop. Both
paths use the same supervisor router and task execution helpers. Agree the
evaluation boundary with the team before running a held-out set; results must
name the entry point. Historical runs made before P3 integration used only the
supervisor path and should not be pooled with graph runs.

Optional `--mlflow` tracking joins configuration parameters, per-question results,
API cost, local CPU/memory, latency and later team grades. See the
[MLflow experiment guide](mlflow_experiments.md). Existing JSON/CSV exports remain.

For routing, corpus availability, retrieval, evidence selection, faithfulness
and correctness diagnostics on a new question list, use the separate
[stage evaluation workflow](stage_evaluation.md) after saving the batch runs.

B adds decomposition to the existing router call. Each task has an ID, target
agent, focused question and required answer elements. Execution uses the focused
question and preserves all task outputs for final synthesis. Repeated price or
policy tasks are supported, with a six-task cap. Invalid task structures or
route/task inconsistencies trigger the router's existing bounded retry and safe
fallback. Structural validation cannot prove that the LLM preserved every
constraint; inspect task traces and grade the final answer against the original
question. Required elements are not a coverage verdict.

There is no new supervisor coverage assessor or replanning loop in A/B. P5's
existing policy assessment/self-correction stays the same in both variants.
Synthesis in B receives task associations and instructions for combining the
results, so this measures the complete decomposition integration, including its
prompt/output token overhead. It is not an experiment isolating each individual
prompt edit. Keep coverage checks (C) and targeted supervisor retry (D) as later
experiments, after freezing the A/B design.

## Run a single question

Both entry points read `supervisor.decompose` in `config.yaml` (currently
`true`; `false` if the key is omitted entirely). Callers can override it per
request without changing shared config:

```python
from agents.supervisor.pipeline import handle_question

baseline = handle_question(question, today="2026-10-28", decompose=False)
decomposed = handle_question(question, today="2026-10-28", decompose=True)

from agents.graph.graph import run

graph_baseline = run(question, today="2026-10-29", decompose=False)
graph_decomposed = run(question, today="2026-10-29", decompose=True)
```

The existing graph CLI now respects the same config setting:

```sh
python -m agents.graph.graph "Since singles can't buy resale flats, what's the cheapest 2-room in Yishun?"
```

There is one decomposition step inside the router, not a second P3 planner.
For this example, the policy task should verify the eligibility claim while
the price task asks for historical transaction statistics. The policy assessor
receives only its focused question. A successful split does not guarantee
sufficient evidence; genuine policy abstentions remain possible. A minimum
recorded transaction is historical and does not establish the cheapest current
listing available to buy.

B returns `task_results`, including the task, raw result, elapsed seconds and
execution error. Usage entries include `task_id` for agent calls. Legacy
`price_result`/`policy_result` fields hold the first successful result of each
type; consumers needing all results should read `task_results`. Synthesis already
does this. No task coverage status is inferred from a successful execution.

P3 stores the latest task records in a dictionary keyed by task ID, merging
updates from its parallel price/policy branches. Before synthesis it creates
the ordered `task_results` list. Self-check agent-error retries rerun only the
failed task IDs with their original focused questions; successful sibling task
results remain available. Synthesis-only retries reuse all task results. The
router is not called again. Task steps and usage include `task_id` and `attempt`;
all reported calls across retries, including policy assessments and self-check,
contribute to `cost_usd`. P3's existing retry limit applies to the whole review
loop; no new coverage reviewer or planner retry is introduced.

## Prepare the team's unseen set

Use a CSV with required `question_id` and `question`, and optional `category`:

```csv
question_id,question,category
U001,"Your team's unseen question",mixed
```

IDs must be unique and nonempty. UTF-8 CSVs with a BOM are accepted. The file
[evaluation/templates/unseen_questions.example.csv](../evaluation/templates/unseen_questions.example.csv)
is a development example, not an unseen benchmark. Replace it with independently
written questions for the actual evaluation.

Include price-only, policy-only, mixed, unsupported, false-premise and dataset
boundary questions. Add comparison questions and cases with one answerable and
one unanswerable part. Choose category definitions and scoring rules before
seeing outputs. Keep reference answers, expected routes, required facts and
reference source dates in a separate reviewer file keyed by question ID.
The runner passes only the question string, fixed date and variant flag into the
pipeline; it ignores additional CSV columns and never passes categories or gold
answers to inference.

Use practice questions for tuning. Freeze code, prompts, model settings, corpus,
transaction snapshot and date before revealing the final held-out set. A revised
prompt after inspecting held-out results needs a new held-out set for a fresh
claim of unseen performance. Do not select only successful questions afterward.

## Run paired A/B evaluation

From the repository root, with the project environment activated:

```sh
python -m agents.supervisor.ablation run evaluation/templates/unseen_questions.example.csv --out evaluation/ablation/dev_check --today 2026-10-28 --repeats 1 --dry-run
python -m agents.supervisor.ablation run /path/to/team_unseen.csv --out evaluation/ablation/team_unseen_v1 --today 2026-10-28 --repeats 3
```

For the team's full P3 workflow, choose the graph explicitly and use a separate
output directory:

```sh
python -m agents.supervisor.ablation run /path/to/team_unseen.csv --pipeline graph --out evaluation/ablation/team_graph_v1 --today 2026-10-29 --repeats 3
```

This compares P3 without decomposition against P3 with decomposition, using
identical `self_check` settings in both variants. Self-check model calls and
retries count toward inference cost. The manifest and run records identify the
selected pipeline; the manifest also records self-check settings. Add
`--dry-run` to validate the schedule without calling models.

Dry-run validates input and prints the number of pipeline runs, with no model
calls or output files. A real run requires real policy configuration, API
credentials, the transaction data and the prepared local policy index. It makes
paid API calls. Three repeats with N questions make 6N pipeline executions;
individual executions can make multiple model calls. Choose a fresh output
directory; existing runs cannot be overwritten.

The runner fixes the date and shuffles A/B order within each question/repeat
using a saved seed. Both use identical shared model/retrieval settings. Model
outputs and remote services can still vary. Local loading caches and API prompt
caching can affect timings; random order helps distribute this effect but does
not eliminate it. Report observed latency rather than claiming cache-free speed.
Run on the same machine and avoid changing files or rebuilding the index during
the experiment. The manifest fingerprints source/prompts/config, corpus, price
files and persisted vector-store files present at the start, including local
uncommitted code. Files missing at startup have a null fingerprint. Fingerprints
are provenance, not a dependency bundle; preserve the matching environment and
artifacts separately.

Output files:

| File | Purpose |
| --- | --- |
| `manifest.json` | Sanitized question set, settings, date, seed, scope and file hashes |
| `runs.jsonl` | Full bundles, tasks/evidence, usage, timings and errors; flushed after each execution |
| `efficiency.json` | Overall and per-category cost/tokens/calls/latency, means, medians, standard deviations and error counts |
| `grading_blind.csv` | Shuffled answers and citations with blank quality grades; hides variant/repeat |
| `review_key.csv` | Mapping from review IDs to variants/repeats; keep away from reviewers until grading |
| `comparison.csv` | Per-variant settings, cost/latency/local compute and quality after grading |
| `mlflow.json` | MLflow parent/child run IDs and store URI, when tracking is enabled |

Run IDs are reproducible from the question ID, repeat and seed; blinding is for
practical reviewer workflow, not cryptographic secrecy. Reviewers should receive
only the blind sheet, rubric and independent references. A separate coordinator
should retain the key and full traces. No automated judge runs in this version,
so inference totals exclude reviewer/judge costs by construction.

## Grade and compare

Have reviewers score against the **original** question and independent reference
facts, not just the generated tasks. Each metric uses 0 to 1; the agreed default
anchors are 0, 0.5 and 1:

| Metric | 1 | 0.5 | 0 |
| --- | --- | --- | --- |
| `correctness` | Correct answer or justified limitation | Material correct content with some errors | Incorrect, misleading or failed execution |
| `completeness` | Covers all requested parts, including explicit unavoidable gaps | Covers some parts | Omits the requested answer or failed execution |
| `groundedness` | Claims supported by supplied evidence/transaction results | Mix of supported and unsupported claims | Unsupported answer or failed execution |
| `appropriate_abstention` | Answers supported parts and declines only unsupported parts | Some over-refusal or unsupported answering | Major refusal error, unsupported answering, or failed execution |

A justified limitation can score well; abstention is not automatically an error.
For mixed questions grade every requested part, including the price component.
Check numeric facts and filters against the frozen transaction snapshot. Check
policy claims and citation support against the frozen sources. Reviewers may
request evidence from the coordinator for verification while retaining variant
blinding. Agree how to handle genuinely ambiguous questions before scoring.
Use a second reviewer and adjudicate disagreements where feasible.

Save the completed sheet under a new name, then run:

```sh
python -m agents.supervisor.ablation score evaluation/ablation/team_unseen_v1 evaluation/ablation/team_unseen_v1/graded.csv
```

The scorer rejects missing grades, out-of-range values, duplicated review IDs
and missing/extra runs. It reports overall/per-category quality means, matched
B-minus-A quality differences, and efficiency. Differences are descriptive,
with one pair per question/repeat; they are not significance tests. Report unique
question count as well as repeats, and do not treat repeats as independent unseen
questions. These graded means are rubric scores, not a binary accuracy rate.

Execution failures remain in the sheet and quality denominators. Grade failed
executions as zero; do not remove them. Agent errors, synthesis errors, router
fallbacks and incomplete usage are also counted. Cost is an estimate at configured
rates, not billing: cache discounts are not modeled, SDK-internal retries may be
unreported, and failed requests can incur costs without returned usage. Report
incomplete-usage counts alongside cost. Reported usage before a pipeline exception
is retained, but any unreported portion of failed-run cost is unknown, not zero.
No accuracy/cost improvement is claimed until actual runs have been graded.

Public supervisor/P3 calls also append the local [usage CSV history](usage_logging.md)
when enabled, including each actual A/B execution. `bundle.usage_tracking.run_id`
links a saved bundle to that history. These CSV rows are another view of the
same calls; do not add their costs to `runs.jsonl` totals or count trace imports
as additional inference. The ablation's own exports remain the experiment record.

## Development smoke test on 29 October 2026

The [saved P3 trace](../evaluation/diagnostics/p3_decomposition_smoke_20261029.json)
records one live development run of the mixed singles-premise/Yishun-price
question. The router created two tasks, policy returned `ANSWER_READY`, and the
final answer retained policy citations and historical price facts. The run took
27.50 seconds and recorded an estimated USD 0.067248 at the configured rates,
including one synthesis retry and two self-check calls. These are observations
from one run, not an accuracy benchmark or a paired cost comparison.

The final self-check remained `weak`, flagging price citation/formatting issues.
Those reviewer findings are retained in the trace; the self-check prompt was
unchanged for this integration. The successful policy task demonstrates that
the full mixed question no longer forces policy assessment to supply transaction
prices. It does not establish that the entire final answer passed review.

An interrupted run preserves completed JSONL records. The grading exports are
written only at normal completion; do not mix a partial run with a completed
experiment. Start a fresh directory for a complete comparable run.

## Export a comparison workbook (Excel)

`agents/supervisor/excel_export.py` builds a formatted `.xlsx` workbook from
saved results. It never runs inference — it only reads `manifest.json`,
`runs.jsonl` and any graded CSV/JSON already on disk. Install the optional
dependency first (shared with MLflow/psutil):

```sh
python -m pip install -r requirements-experiments.txt
```

Build it automatically as part of a run or a scoring pass:

```sh
python -m agents.supervisor.ablation run evaluation/templates/unseen_questions.example.csv --out evaluation/ablation/dev_check --today 2026-10-29 --excel
python -m agents.supervisor.ablation score evaluation/ablation/top10_review evaluation/ablation/top10_review/graded.csv --excel
```

Or build/rebuild one later, without rerunning inference, from one or more
saved run directories and/or a historical single-question trace JSON (a
bundle returned by `handle_question()`/`run()`, saved separately):

```sh
python -m agents.supervisor.ablation export-excel evaluation/ablation/top10_review evaluation/ablation/top5_no_review --out evaluation/ablation/setup_comparison.xlsx
python -m agents.supervisor.ablation export-excel --trace path/to/saved_bundle.json --out evaluation/ablation/single_trace.xlsx
```

From Python:

```python
from agents.supervisor.excel_export import export_workbook

export_workbook(["evaluation/ablation/top10_review"], "evaluation/ablation/top10_review/experiment.xlsx")
```

The workbook has three sheets: **Parameters** (requested vs. applied config
per experiment/variant, with override/provenance notes), **Calls** (one row
per reported usage entry — stage, task ID, attempt, tokens, calculated cost,
timing and grades, with the question/answer/outcome shown once per run) and
**Comparison** (per-experiment/variant quality and cost rollups, computed
with live spreadsheet formulas so a reader can audit them against the Calls
sheet). A trace-only group is marked "Partial historical trace" since it has
no saved config snapshot, compute measurement or grades.

## Local compute measurement

`agents/supervisor/compute_metrics.py` records this Python process's CPU-time
delta and sampled peak RSS for every `ablation run` execution (regardless of
`--mlflow`), using `experiment_tracking.memory_sampling_interval_seconds` from
`config.yaml` as the sampling interval; `machine_info()` records the Python
version, platform, CPU count and total RAM once per batch into
`manifest.json`. These describe the local process only, not the hosted
model's compute — see the fuller caveats in
[mlflow_experiments.md](mlflow_experiments.md#measurements-and-their-limits).

There is no separate CLI for this; it runs automatically inside
`run_experiment()`. To measure a block of code directly from Python:

```python
from agents.supervisor.compute_metrics import ProcessMeasurement, machine_info

with ProcessMeasurement(interval=0.1) as measurement:
    ...  # code to measure
print(measurement.metrics)
print(machine_info())
```
