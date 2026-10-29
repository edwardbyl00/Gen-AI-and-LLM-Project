# Change Log

A running record of what changed in the supervisor/RAG work, in plain
English, so you (or a teammate) can see what happened and why without
re-reading every diff.

**How to use this file:** newest entry at the top. One entry per logical
change (not per commit). Each entry: a one-line summary, what actually
changed, and *why* — the why is the part worth writing down, since the
diff already shows the what. Mark whether it's still uncommitted.

---

## 2026-10-29 — Added MLflow parameter, cost and compute experiment tracking

**Status:** uncommitted

- Added optional MLflow tracking to the existing paired evaluator with one
  parent per batch and child runs per question/variant/repeat. Preserved local
  JSON/CSV exports and linked them through `mlflow.json` and child run IDs.
- Stored original questions/IDs, answers, decomposed tasks, retrieved evidence
  and errors in each child run's `result.json` artifact; the parent manifest
  includes the question set. These are experiment artifacts, not a chat-history
  view. Reference answers and grades are not passed to pipeline inference.
- Saved searchable model/request, retrieval, price and self-check parameters,
  applied A/B overrides, setup IDs, full configuration/prompt snapshots,
  source/data hashes, code revision, package versions and machine information.
- Logged reported API tokens/calls/configured-rate USD cost and stage totals,
  errors/retries, latency, local process CPU time and sampled RSS memory.
  These local measurements do not claim provider CPU/GPU, energy or billing.
- Added `score --publish-mlflow` to attach independent team grades to original
  runs without repeating inference. Added per-variant `comparison.csv` exports
  and a `compare` command that filters by quality thresholds and marks cost/
  latency/CPU/memory trade-offs rather than declaring the cheapest answer best.
- Added config-drift checks to prevent settings changing within a batch and a
  cached-model guard for fresh-process configuration experiments. Kept model
  grading optional; tracking itself makes no LLM calls.
- Installed pinned optional dependencies from `requirements-experiments.txt`,
  initialized the local SQLite store, and added the
  [MLflow experiment guide](mlflow_experiments.md). Local tracking storage is
  ignored by Git; normal single-question CLI runs retain CSV logging.
- Clarified that MLflow records evaluator runs enabled through `--mlflow` or
  `experiment_tracking.enabled`; standalone supervisor/P3 CLI calls continue
  to save question/consumption history in CSV without creating MLflow runs.

**Why:** the team needs a unified record linking actual setup parameters and
independently reviewed quality to API cost and local resource use, so a cheaper
configuration can be assessed against answer quality rather than token count alone.

**Verified:** 180 offline tests passed, including real SQLite MLflow parameters,
metrics, artifacts, grade updates, failure handling, configuration drift and
quality-constrained comparison. Dependency checks passed. The local MLflow
health/UI endpoints returned HTTP 200. No model API calls were made for this
integration's verification; no best-performing configuration is claimed yet.

---

## 2026-10-29 — Added automatic CSV consumption history

**Status:** implementation included in `7a36d49`; documentation and regression-runner updates uncommitted

- Supervisor and P3 public entry points now append one local summary row per
  run to `logs/usage/runs.csv`, with stage/task entries in `calls.csv` joined by
  a generated run ID. Logging adds no model calls.
- Recorded Singapore timestamps, questions, pipeline/variant, model-call and
  token totals, estimated USD cost, duration, retry cycles, review status and
  incomplete-usage flags. Saved configured model/pricing rates with each run.
- Included failed runs and any reported usage; unknown counts/costs remain blank
  rather than appearing as zero. Logging I/O errors preserve the original answer
  or exception. Locked appends prevent concurrent writes from mixing rows.
- Enabled logging through `usage_logging` configuration, with per-request
  `log_usage=False` overrides. Default logs are ignored by Git. Offline tests
  disable persistent history, while logging tests use temporary directories.
- Added an idempotent saved-trace import and imported the existing P3 smoke
  trace as `source=trace_import`: seven reported calls, 19,999 tokens and
  estimated USD 0.067248. This import did not make another API call.
- Added the [usage log guide](usage_logging.md), updated export documentation
  and included logging tests in the consolidated regression runner.

**Why:** terminal output and experiment-specific JSON files did not provide a
simple cumulative view of normal question costs. The two CSVs let the team view
per-question consumption and identify expensive stages without rerunning models.

**Verified:** 172 offline tests passed across usage logging, supervisor, P3,
pricing and P5 integration. CSV readback confirmed the saved smoke trace's totals,
seven stage entries, UTF-8 headers and Git exclusion. Cost estimates are based on
reported tokens and configured rates, not provider billing records.

---

## 2026-10-29 — Extended decomposition to the P3 graph; made it the default

**Status:** committed in `7a36d49`

- Extracted the routing/task logic shared by the sequential pipeline into
  `agents/supervisor/tasks.py` (`resolve_decompose()`, `route_with_tasks()`,
  `tasks_for_route()`, `execute_task()`), replacing `pipeline.py`'s private
  `AGENTS_FOR_ROUTE` map and inline task-execution code.
- `agents/graph/graph.py` (P3) now builds on the same helpers: its agent
  nodes run per-task in parallel branches, its self-check loop retries only
  the failed task IDs (not the whole question), and `code_checks()` reads
  the same aggregated evidence `synthesis.build_context()` uses so it stays
  consistent with what synthesis actually saw.
- `agents/supervisor/ablation.py` takes `--pipeline {supervisor,graph}` so
  the A/B runner can evaluate either entry point; the manifest and each
  run record now also save which one was used. Graph A/B runs retain identical
  self-check settings, and summaries count weak verdicts and review errors.
- P3 now logs policy-assessor calls alongside routing, pricing, synthesis and
  self-check usage. Task calls carry task IDs and attempt numbers; the final
  state includes estimated total cost and end-to-end elapsed time.
- Flipped `config.yaml`'s `supervisor.decompose` from `false` to `true`,
  making decomposition (B) the default for both entry points rather than
  opt-in; `decompose=False` still runs the plain baseline.
- Updated `README.md`, `p2_supervisor_code.md` and `supervisor_ablation.md`
  to describe `tasks.py`, the P3 graph's decomposition support and the new
  default.

**Why:** the P3 CLI previously ignored the decomposition flag and sent the
full mixed question to policy retrieval. For "Since singles can't buy resale
flats, what's the cheapest 2-room in Yishun?", the assessor found evidence to
check the eligibility premise but abstained because policy passages did not
also contain transaction prices. The shared helpers let P3 execute the
supervisor's focused tasks, with one decomposition step rather than a second
planner. Policy assesses eligibility evidence; the price agent supplies
historical transaction statistics.

**Verified:** 162 offline tests passed across supervisor, graph, pricing and
P5 integration; the graph ablation dry-run passed. Baseline tests now pass
`decompose=False` explicitly where they depend on the one-task-per-agent
behavior. Added `tests/test_graph_decomposition.py` for focused mixed-question
execution, parallel result merging, targeted retries, evidence checks,
configuration overrides and usage accounting.

**Live development check:** one run of the mixed singles-premise/Yishun-price question created
two focused tasks and returned policy `ANSWER_READY` with cited policy evidence.
The [development trace](../evaluation/diagnostics/p3_decomposition_smoke_20261029.json)
records 27.50 seconds and estimated USD 0.067248, including self-check/rewrite
calls. These measurements describe one development run, not a graded A/B
benchmark or evidence of an overall accuracy improvement.

**Remaining issue:** final self-check remained `weak`, flagging price
citation/formatting after its bounded rewrite. Its review prompt was unchanged;
resolving the policy abstention does not mean the full answer passed review.
Supervisor coverage assessment and replanning remain deferred.

---

## 2026-10-28 — Optional supervisor decomposition and paired A/B evaluation

**Status:** committed in `b709f92`

- Added router-generated focused tasks behind `supervisor.decompose`, retaining
  the existing baseline as the default. Synthesis receives all task results,
  with separate transaction facts and policy decisions.
- Added a paired A/B runner for unseen question CSVs, task/usage traces, file
  fingerprints, repeated runs, blinded grading and category-level quality/cost
  summaries. References stay outside inference and failures remain in scoring.
- Documented team preparation, fixed snapshots, grading and the evaluation
  boundary: the supervisor pipeline, excluding the separate P3 self-check graph.
- Deferred supervisor coverage assessment and replanning to later ablations so
  this comparison isolates the decomposition integration.

**Why:** keep transaction requests out of policy retrieval subquestions and
measure the cost and answer-quality impact of decomposition, while supporting
the team's evaluation on unseen questions without exposing reference answers
to the pipeline.

**Verified at implementation:** 150 offline tests passed across supervisor, pricing, P5 integration
and graph regressions. The example evaluation dry-run passed without API calls.
No paid A/B evaluation or accuracy comparison is recorded for this change.

---

## 2026-10-28 — Re-fixed the API key lookup, and applied it to the two judge modules too

**Status:** committed in `b709f92`

`src/evidence_assessor.py` was back to reading only `OPENAI_API_KEY`, raising
`ValueError` for anyone whose `.env` uses `LLM_API_KEY` (the fallback
`router.py` already uses). Widened the lookup again and reworded the error
to name both variable names. Found the same single-key lookup in
`src/ground_truth_judge.py` and `src/llm_judge.py` and applied the identical
fix there, so all four modules that build an OpenAI client now accept either
variable name consistently.

**Why:** this exact fallback was added once already in `f9e2fae` but was
lost when a later merge (`1d38dca`, completing the P5 agentic RAG
integration) brought in an older copy of `evidence_assessor.py` without it.
`ground_truth_judge.py` and `llm_judge.py` never had the fallback at all —
fixed now for consistency with `router.py` and `evidence_assessor.py`.

---

## 2026-10-25 — Added the supervisor routing evaluation report

**Status:** committed in `a006695`

Added [reports/routing_report.md](../reports/routing_report.md), summarizing
the saved 54-question routing evaluations, the v2 prompt changes and remaining
errors involving procedures, personal-finance routing and implicit premises.
The report covers routing only, not final-answer accuracy or decomposition.

**Why:** give the team a readable account of the saved routing results and
the cases to review before further prompt tuning. As documented in the
supervisor guide, v1's `false_belief` and v2's `check_premise` have different
meanings; their premise scores are not a like-for-like improvement measure.

---

## 2026-10-25 — Updated P2 guide and shared usage/cost tracking

**Status:** committed in `929a961`

- Documented the current supervisor interfaces: price is always real, policy
  remains configurable, and selected agents accept `usage_log`.
- Shared usage now includes price filter/SQL calls and aggregated policy
  assessor calls. The pipeline returns estimated `cost_usd`; answer exports
  include it and print a run total using `llm.pricing` configuration.
- Kept the high-level flow and added pricing decision branches as an
  integration reference. Specialist pricing and data-preparation guides
  remain outside this documentation pass.
- Clarified the nine v2 label columns, manual grading, legacy-label limits,
  UTF-8 CSV import, export coverage and comparisons across saved runs.
- Fixed the project README's link to the removed process guide.

**Why:** align P2 documentation with code and avoid presenting incomplete
usage totals, changed labels or old stub runs as comparable current results.

**Verified:** 157 local tests passed; documentation links and diff checks
passed. No paid evaluations were rerun for this documentation pass. The
v2 routing CSV was included in `929a961`.

Historical entries below describe the state at their recorded change.
Their verification counts are historical, not a new validation of this tree.

---

## 2026-10-25 — Router flags premises to check, not false beliefs

**Status:** committed in `78dbc0d`; labels subsequently cleaned in `e6c5552`

Replaced the routing field `false_belief` with `check_premise`, and added
router prompt `supervisor_v2.md` and synthesis prompt `synthesis_v2.md`
(both v1 files kept for comparison).

- **What the flag means now:** the question states or assumes a specific
  claim about HDB/CPF rules, schemes, amounts, timelines or procedures, or
  about resale prices. The router no longer decides whether the claim is
  true. Facts about the user's own situation and the status of a service
  do not count.
- **Synthesis A1:** checks the claim against the evidence; corrects it if
  contradicted, simply answers if supported, says it could not confirm if
  the sources are silent.
- **Labels:** `practice_routing.csv` now has `check_premise` and
  `premise_false` (is the claim actually false?), with a
  `premise_rationale` at that stage. Later cleanup moved label history to
  `data/labels/history/practice_routing_label_history.csv`; the active file
  now has nine columns. Drafted labels: 12 premises, 5 known false, 1 known true, 6 to verify.
- **Scores:** `evaluate.py` reports premise detection, myths among them and
  false alarms; myth acceptance in `score_answers.py` uses rows where
  `premise_false` is TRUE. Older answer sheets with `label_false_belief`
  still score.

**Why:** the router cannot see the sources, so asking it whether a claim
is *false* made it rely on the model's memory, the failure the project is
built to avoid. The label audit on 25 Oct also showed that "user makes a
claim" was the natural labelling test. Now the router only detects claims
(a reading task), and synthesis verifies them against dated evidence.

**Note for comparisons:** v1's `false_belief` and v2's `check_premise`
measure different things, so compare v1 and v2 on `route` and
`answerable`, and report premise detection for v2 only.

---

## 2026-10-25 — Connected the real price agent

**Status:** committed in `7fb40fc`; later price-stub retirement and usage updates are documented above

Imported `agents/price/`, `scripts/clean_prices.py`, the cleaned transaction
CSV and pricing tests from `origin/price-agent` at `4f4a027`. Preserved the
existing policy integration and configuration. The teammate's UI, baseline
and comparison harness were not included in this integration.

- `price_real()` now calls `run_price_agent()`; `agents.price` is `real`.
- Added the price settings with approach A (filter extraction + Python
  statistics) as the default; approach B (SQL) remains selectable.
- Synthesis now receives `mean_price` and the price agent's `note`, including
  explanations for missing data or resolved periods.
- Upgraded local pandas from 2.2.2 to 3.1.0 and pinned it in requirements:
  the old version crashed under Python 3.14 in date conversion tests.
- Updated the supervisor guide and added adapter, real-data, missing-data
  context and SQL-selection tests. Price-token tracking is not yet wired
  into the supervisor's shared usage log.

**Verified:** 153 tests passed without paid model calls. A separate live
pipeline smoke test answered the Toa Payoh 4-room 2024 question with 299
transactions, matching an independent count of the supplied CSV. Dataset:
242,955 transactions, January 2017 to October 2026.

---

## 2026-10-25 — Connected the real policy agent; policy retrieval is no longer a stub

**Status:** committed in `f9e2fae`

The policy side of the pipeline went from "returns one fake passage" to
"real hybrid retrieval over the real HDB/CPF corpus, with an LLM evidence
check." Current integration details are in the agent configuration section
of [the supervisor guide](p2_supervisor_code.md#agent-configuration-and-integration).

**What changed:**
- Pulled in from a teammate's branch (`kay`) — not written here:
  - `src/policy_agent.py`, `policy_retriever.py`, `retrieval.py`,
    `hybrid_retriever.py`, `dense_retriever.py`, `chunk_adapter.py`,
    `date_utils.py`, `evidence_assessor.py`
  - `scripts/chunking.py` (rewritten to chunk by the embedding model's own
    tokenizer), `generate_embeddings.py`, `build_chroma_db.py`,
    `query_chroma_db.py`, `validate_chroma_consistency.py`,
    `evaluate_dense_retrieval.py`
  - The real prepared corpus, `data/processed/chunks.jsonl` (1,282 chunks,
    replacing the branch's previous 587-chunk file), plus mock fixture
    data (`data/mock/`) and matching test files
    (`test_retrieval.py`, `test_dates.py`, `test_data_integration.py`,
    `test_dense_retrieval.py`, `test_embeddings.py`, `test_policy_agent.py`,
    `test_chroma_db.py`, `test_p5_integration.py`,
    `test_p5_agentic_control.py`, and a matching `test_chunking.py`)
- **`agents/supervisor/adapters.py`** — `policy_real()` rewritten to call
  `run_policy_agent()` (hybrid BM25 + dense retrieval, automatic re-query,
  an LLM evidence check with one self-correction pass) instead of the
  plain retriever. Its richer `{"decision", "reason", "retrieval",
  "trace"}` output is flattened back to the `{"evidence": [...]}` shape
  synthesis already expects; an "abstain" decision is mapped onto an
  empty evidence list, so no other pipeline code needed to change.
- **`config.yaml`** — `agents.policy` set to `real` (was `stub`);
  `policy_top_k` raised from 3 to 10; added the `data_preparation.chunking`
  settings that produced the new corpus, plus new `embedding` and
  `vector_store` sections the build scripts read.
- **`requirements.txt`** — added `rank-bm25`, `chromadb`, `numpy`, `torch`,
  `transformers`. The latter three are pinned to newer versions than the
  teammate's branch uses, because those older pins have no wheel for this
  project's Python 3.14.
- **`.gitignore`** — added `data/embeddings/` and `data/vector_db/`:
  generated locally, not committed (matches the teammate's branch).
- Built locally (not committed, regenerate if the corpus changes):
  `data/embeddings/bge-base-en-v1.5/` (via `generate_embeddings.py`) and
  `data/vector_db/chroma/` (via `build_chroma_db.py`).

**Two bugs fixed in the pulled-in code** (compatibility fixes, not logic
changes):
- `src/evidence_assessor.py` only read `OPENAI_API_KEY`; this project's
  `.env` stores the key as `LLM_API_KEY`. Widened the lookup to match the
  fallback `router.py` already uses.
- `scripts/chroma_db.py`'s `collection_metadata()` passed `None` through
  for an unset model revision (the manifest key exists but is `null`, so
  `.get(key, default)`'s default never fired). The installed Chroma
  version rejects `None` as a metadata value. Fixed to
  `.get("model_revision") or "unrecorded"`.

**One test deliberately left out:** `test_p5_integration.py` had a test
for a separate `src/pipeline.py` (an LLM-judge evaluation harness)
unrelated to this integration; that module wasn't pulled in, so the test
was removed with a comment explaining why, rather than pulling in an
out-of-scope module just to make it pass.

**Why:** the RAG team reported their retrieval stack as done. The price
agent is still a stub — same mechanism to connect it later
(`price_real()` in `adapters.py`, flip `agents.price` to `real`).

**Verified:** `python -m pytest tests/ -q` → 129 passed. Ran a real
question through `python -m agents.supervisor.pipeline` end to end and
got a correctly-cited answer from real retrieved passages.

---

## 2026-10-24/25 — Wrote up the supervisor documentation

**Status:** documented in `f9e2fae`, with later revisions

Rewrote `Docs/p2_supervisor_code.md` from scratch in plain English (the
previous version, along with `PROJECT_PROCESS.md`, `p2_supervisor_contract.md`
and `routing_spec.md`, was deleted as part of an intentional docs cleanup).

**What it covers:**
- The whole-flow picture and a worked example tracing one question through
  every file.
- Every file in `agents/supervisor/` individually: `pipeline.py`,
  `router.py`, `checks.py`, `adapters.py`, `synthesis.py`, `evaluate.py`,
  and the new `score_answers.py` (which had no prior documentation).
- How to change a prompt safely, and — the part that's easy to get
  wrong — which rules are enforced by the prompt text alone versus which
  are hard-coded checks in `checks.py`/`synthesis.py`.
- Step by step: how to write a labelled question, run `evaluate.py` to
  score routing, and run `score_answers.py`'s run → grade → score cycle
  for final-answer quality.
- Settings, day-to-day commands, and troubleshooting, folded into this one
  file instead of a separate maintenance doc, since it reads as one
  coherent story about this part of the codebase.

**Why:** so the supervisor's behavior, its safety nets, and its tuning
loop are documented from the code as it actually is today, not from
whatever an older doc said before the recent changes (`usage_log`/cost
tracking, `score_answers.py`) landed.

---

## Undated — cost tracking and answer scoring (already in progress before this log started)

**Status:** historical work already present before this changelog; see Git history

These were already sitting as uncommitted changes when this log was
started, and are documented here for completeness rather than invented
after the fact — see `Docs/p2_supervisor_code.md` for the full detail.

- `router.py` / `synthesis.py` / `pipeline.py`: added a shared `usage_log`
  so every model call's token counts are recorded on the bundle
  (`bundle["usage"]`), for cost tracking.
- Added `agents/supervisor/score_answers.py` and
  `tests/test_supervisor_score_answers.py`: the run → grade → score
  workflow for scoring final answers on honesty and myth-acceptance,
  separate from `evaluate.py`'s routing-only scoring.
