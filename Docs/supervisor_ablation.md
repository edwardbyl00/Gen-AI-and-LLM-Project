# Supervisor decomposition ablation and unseen-question evaluation

This first experiment compares A (the existing supervisor) with B (the same
supervisor with router-generated tasks). It runs routing, the selected real
price/policy agents, and final synthesis. It does **not** run the separate P3
LangGraph/self-check entry point. Agree this evaluation boundary with the team
before running a held-out set; results must name the entry point.

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

`config.yaml` keeps `supervisor.decompose: false` by default. Callers can choose
per request without changing shared config:

```python
from agents.supervisor.pipeline import handle_question

baseline = handle_question(question, today="2026-10-28", decompose=False)
decomposed = handle_question(question, today="2026-10-28", decompose=True)
```

B returns `task_results`, including the task, raw result, elapsed seconds and
execution error. Usage entries include `task_id` for agent calls. Legacy
`price_result`/`policy_result` fields hold the first successful result of each
type; consumers needing all results should read `task_results`. Synthesis already
does this. No task coverage status is inferred from a successful execution.

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

An interrupted run preserves completed JSONL records. The grading exports are
written only at normal completion; do not mix a partial run with a completed
experiment. Start a fresh directory for a complete comparable run.
