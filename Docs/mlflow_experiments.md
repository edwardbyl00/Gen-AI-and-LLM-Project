# MLflow experiments: settings, quality, API cost and local compute

The paired evaluator can now log to MLflow while keeping JSON/CSV exports.
There is one parent run per evaluation batch and one child run per question,
variant and repeat. Tracking adds no LLM calls. Team-reviewed quality scores
can be attached later without rerunning inference.

## Install and open the UI

From the repository root, with the project's virtual environment active:

```sh
python -m pip install -r requirements-experiments.txt
mlflow server --backend-store-uri sqlite:///logs/mlflow/mlflow.db --host 127.0.0.1 --port 5001 --workers 1
```

Open <http://127.0.0.1:5001>. The default local database and artifacts live under
`logs/mlflow/`, which is ignored by Git. CSV history remains in `logs/usage/`.
Normal single-question supervisor/P3 CLI runs still write CSV; MLflow is enabled
for the experiment runner with `--mlflow` or `experiment_tracking.enabled`.

The optional requirements pin the MLflow and psutil versions verified with this
project's Python 3.14 environment. They are separate from the core application
requirements. A shared server can later replace the local SQLite URI; teammates
need the same tracking endpoint and artifact access to see the same records.

## Run an experiment

Use a development set first. Validate the planned calls/settings with:

```sh
python -m agents.supervisor.ablation run evaluation/templates/unseen_questions.example.csv --pipeline graph --mlflow --out evaluation/ablation/dev_top10_review --run-name dev_top10_review --today 2026-10-29 --repeats 3 --dry-run
```

Remove `--dry-run` to execute. That makes paid model calls. A/B always runs the
same questions with decomposition disabled/enabled; other settings stay fixed.
An existing output directory is never overwritten. For the final unseen set,
replace the example CSV with the independent question-only file agreed by the
team, after freezing prompts, settings and references.

```sh
python -m agents.supervisor.ablation run /path/to/team_unseen.csv --pipeline graph --mlflow --out evaluation/ablation/top10_review --run-name top10_review --today 2026-10-29 --repeats 3
```

Optional `--tracking-uri` and `--experiment-name` select another store/experiment.
URI precedence is the CLI argument, then `MLFLOW_TRACKING_URI`, then config.
`--no-mlflow` explicitly disables tracking for a batch. Dry-run never initializes
MLflow or makes inference calls.

## Settings recorded for each setup

The batch retains the config snapshot, file fingerprints, exact prompt files,
fixed date, question-set hash, code revision/dirty state, installed package
versions and machine information. The child runs log the configuration as
searchable `config.*` parameters, including:

| Settings | Examples |
| --- | --- |
| Model/request | Model name, temperature, seed, output cap, timeout |
| Supervisor | Requested decomposition setting and applied A/B override |
| Policy retrieval | Real/stub selection and policy `top_k` |
| Review | LLM self-check flag and retry limit |
| Price agent | A/B approach, default period and dataset paths |
| Data preparation | Chunking/embedding/vector-store settings associated with the index |
| Cost assumptions | Input/output USD rates per million tokens |

`effective.*` parameters distinguish runtime overrides from requested config.
For example baseline A has `effective.supervisor.decompose=false` even when the
config default is true. The sequential pipeline reports self-check disabled
because it does not execute P3's reviewer. `setup_id` identifies the effective
configuration/pipeline; code/data fingerprints identify the surrounding revision.
Build-time embedding/chunking settings are provenance, not promises that changing
a YAML value rebuilds an index. Follow the index build workflow when varying them.

Change `config.yaml` **between** experiments and launch a fresh CLI process for
each setup. Some policy modules cache the model at import time. The evaluator
checks the config before and after each question and stops if it changes during
a batch. Completed records are retained, but an interrupted/drifting batch cannot
be scored as a complete comparable experiment. Keep source/data files fixed too;
their initial hashes document provenance but do not lock the files on disk.

Start with one factor at a time: self-check on/off, then `policy_top_k` 10/5,
then the price approach if relevant. Use a distinct run name/output directory
for every setting. If changing the model, also update the configured pricing.
The runner records settings; it does not silently modify config or run a paid
parameter sweep.

## Measurements and their limits

Each child run records:

- Reported input/output tokens, call count, configured-rate USD estimate and
  per-stage token/cost totals, including repeated synthesis/review calls.
- End-to-end pipeline wall-clock seconds, retry count, errors and weak reviews.
- Local process CPU-time delta and sampled RSS memory: start, peak, end, delta
  and sample count. The sampling interval is recorded, and missing measurements
  stay unknown rather than becoming zero.
- Full result bundle/answer, task/evidence traces and the CSV history run ID
  when the public entry point saved one.

The local measurements cover this Python process, including retrieval and
instrumentation, but not child processes or the remote provider's CPU/GPU.
CPU time can exceed wall time when multiple local threads execute. RSS includes
cached models/data already resident from earlier questions; the peak is sampled,
not a guaranteed instantaneous maximum. No GPU utilization, energy consumption
or dollar price for local CPU is claimed. API dollars, CPU-seconds, memory and
latency are separate axes. Tokens are observable API usage, not a measurement
of the provider's hardware consumption.

MLflow writes happen outside the per-question pipeline measurement. Existing
CSV logging and the small sampling overhead are inside it. MLflow startup,
artifact upload and source hashing are not included in the pipeline latency.
Randomized A/B order helps distribute cache effects; use repeated runs on the
same machine and report cold/warm behavior rather than claiming cache-free speed.
Keep tracking and sampling settings identical when comparing configurations.

Failures remain in quality denominators. Inspect `usage_incomplete` before
comparing cost: missing usage or rates must not make a failing setup look cheap.
The MLflow cost metric uses the same configured-rate estimate as the evaluator;
automatic provider-price lookup/autologging is not enabled in this integration.
Tracking is separate from optional LLM judges, whose calls would have their own
cost. API estimates may differ from billing because of retries/cache discounts.

## Add team grades

Keep reviewers blind to variants. The coordinator keeps MLflow and the review
key; reviewers receive the blind sheet, rubric and independent references.
After review, save a completed `graded.csv`, then validate and publish:

```sh
python -m agents.supervisor.ablation score evaluation/ablation/top10_review evaluation/ablation/top10_review/graded.csv --publish-mlflow
```

This attaches `quality.correctness`, `quality.completeness`, `quality.groundedness`
and `quality.appropriate_abstention` to the original child runs, and variant
means/paired differences to the parent. No inference is rerun. It also saves
`quality_scores.json` and refreshes `comparison.csv`. Invalid or incomplete
sheets are rejected before publishing. These are rubric scores on a 0–1 scale,
not an automatically measured binary accuracy rate. A self-check pass is not
used as a substitute for independently graded correctness.

## Compare cost-effective settings

In MLflow, select question runs to inspect applied parameters and per-question
metrics, or compare batch runs using `A_baseline.*` and `B_decomposition.*`
aggregate metrics. Each local `comparison.csv` has one row per variant/setup
with settings, cost, CPU/memory/latency summaries and reviewed quality.

Combine several graded setups with explicit quality thresholds:

```sh
python -m agents.supervisor.ablation compare evaluation/ablation/top10_review evaluation/ablation/top5_no_review --min-correctness 0.8 --min-completeness 0.8 --out evaluation/ablation/setup_comparison.csv
```

The tool requires the same question-set hash and fixed date. A row is eligible
only when its correctness/completeness meet the chosen thresholds, reported
usage is complete, and all four cost/compute measures are available. It marks
Pareto-efficient rows: no other eligible row is at least as good in API cost,
wall time, CPU time and RSS peak and strictly better on one of those measures.
Several setups may remain because lower API cost can trade off with more CPU
or memory. This does not choose a universal winner or make significance claims.
Review groundedness, source revisions, hardware and score variation as well.
Ungraded runs cannot qualify. Thresholds are your evaluation choices, not built-in
claims about acceptable answer quality.

`mlflow.json` links the local records/review IDs to MLflow runs. Keep it with the
experiment directory for later grade uploads. JSON/CSV/MLflow describe the same
executions; do not add their totals together. Avoid using the held-out set for
iterative tuning; improvements after inspecting it need a new held-out set.

Implementation references: [MLflow tracking](https://mlflow.org/docs/latest/ml/tracking/),
[client API](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.client.html),
[local tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).
