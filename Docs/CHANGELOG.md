# Change Log

A running record of what changed in the supervisor/RAG work, in plain
English, so you (or a teammate) can see what happened and why without
re-reading every diff.

**How to use this file:** newest entry at the top. One entry per logical
change (not per commit). Each entry: a one-line summary, what actually
changed, and *why* — the why is the part worth writing down, since the
diff already shows the what. Mark whether it's still uncommitted.

---

## 2026-10-31 — Simplified evaluation commands for copying and pasting

**Status:** uncommitted

**Who:** Ed

- Added six ordered steps at the start of the evaluation guide, with the batch
  name and date set once and reused in every command.
- Put question editing before reference generation, backed up existing
  references before regeneration, and used separate timestamped review folders
  to avoid overwriting human grades when preparing another report.
- Kept the detailed rubric and optional judge instructions below the practical
  steps. Explained which commands make paid calls and how to produce the final
  summary from the reviewed CSV.

**Why:** commands should be easy to paste in sequence without mismatched paths,
stale example references or an existing review directory blocking the next step.

## 2026-10-31 — Allow ablation runs to overwrite generated results

**Status:** uncommitted

**Who:** Ed

- Reusing `ablation run --out` now replaces generated run files rather than
  raising `FileExistsError`. Old quality scores, Excel exports, review folders
  and default sibling judge-score files are cleared before new inference so
  they cannot be mistaken for results from the new run. Input and unrelated
  files are preserved; dry runs remain read-only.
- Updated the CLI help and evaluation guides, and added a regression test for
  rerunning with fewer repeats and no judge while preserving inputs and notes.

**Why:** the same evaluation command can be rerun without manually deleting its
output directory or picking a new name.

**Verified:** 20 experiment/decomposition tests passed with the LLM judge
mocked; no paid model calls or existing evaluation runs were made.

## 2026-10-31 — Consolidated the evaluation documentation into one guide

**Status:** committed with this entry

**Who:** Ed

- Combined the step-by-step walkthrough and stage evaluation reference in
  [the evaluation guide](stage_evaluation.md), keeping the batch commands,
  judge options, diagnostic checks, grading rules and report export instructions.
- Removed the duplicate walkthrough and updated the README to point to the
  single guide. Added workflow navigation and troubleshooting so the team can
  run and review an evaluation without switching between two guides.
- Made the diagnostic preparation command work without the optional
  reference-based judge file, and explained how to include it when available.

**Why:** one maintained guide makes the workflow easier to follow and avoids
duplicating instructions that could drift apart.

**Verified:** checked 14 guide links and heading anchors, confirmed no stale
walkthrough links remained, and ran `git diff --check`. Documentation only;
no model calls or evaluation runs were made.

## 2026-10-31 — Run the ungated LLM judge automatically after every ablation run

**Status:** uncommitted

**Who:** Ed

- `agents.supervisor.ablation run` now calls `scripts/judge_ablation_answers.py`
  automatically once `runs.jsonl` is written, defaulting `judge=True` in
  `run_experiment()` and writing `evaluation/ablation/<run-name>_llm_judge_scores.json`
  the same way the script does when run by hand. Added a `--no-judge` CLI flag
  to skip it (extra paid judge calls, or when you only want the gated
  `prepass` scores). Why: the ungated judge was previously an easy-to-forget
  manual step; defaulting it on means every saved run gets a first-read score
  without someone remembering to invoke the script separately.
- Documented the new default behavior and the opt-out flag in
  [stage_evaluation.md](stage_evaluation.md#alternative-judge-without-verified-references).

## 2026-10-31 — Added an ungated first-read judge and count-based citation precision

**Status:** implementation committed in `b629268`/`e85bbc2`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Added `scripts/judge_ablation_answers.py`, which scores every execution in a
  saved ablation run with the existing faithfulness-style judge
  (`src/llm_judge.py`), using only the question, the final answer and the
  policy evidence actually supplied to synthesis. Unlike
  `agents.supervisor.judge_tools prepass`'s gated ground-truth judge, it needs
  no verified reference and is not restricted to the `policy` route, so it can
  give a first read before references exist. Output is a separate
  `*_llm_judge_scores.json`, read only by the Excel export below.
- Surfaced the judge's five rubric criteria (`evidence_support`,
  `policy_currency`, `citation_relevance`, `unsupported_claims`,
  `appropriate_abstention`) as individual numeric columns in the stage-review
  workbook's Review sheet, instead of one packed text cell, so they sort,
  filter and pivot.
- Added citation precision to the same sheet and to Summary: valid cited
  passage numbers over everything the model attempted to cite, reconstructed
  from synthesis's recorded `invalid_citation` events. This is a plain count,
  not a judgement call, and reads "NA" rather than 0 when nothing was cited.

**Why:** before a human has graded `review.csv` or verified references, the
team still wanted a fast, auditable first read on the saved batch — part of it
from an LLM judge (clearly labelled unvalidated, per
[llm_judge_validation.md](llm_judge_validation.md)), part of it a genuine
count that needs no model call at all.

**Verified:** 13 tests passed covering the judge script and the workbook
export (judge/no-judge paths, sheet layout, citation counts); full suite 336
passed. One real judge batch call was made against the saved six-question,
two-variant run (12 executions, ≈$0.08), producing
`evaluation/ablation/new_questions_v1_llm_judge_scores.json`; no new live
pipeline inference was run.

---

## 2026-10-31 — Removed the unused v1 prompt files

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Deleted `agents/supervisor/prompts/supervisor_v1.md` and `synthesis_v1.md`:
  neither is loaded (`router.py`/`synthesis.py` both point at `_v2.md`), and
  the supervisor guide's own prompt-change convention of keeping an old
  version "for comparison" had left them stale once v2 diverged.
- Fixed the docstring pointers in `router.py` and `synthesis.py` that still
  named `supervisor_v1.md`/`synthesis_v1.md` as the live rules reference, and
  corrected the supervisor guide's prompt table (stale `R1–R5`/`A1–A8` ranges,
  "v1 kept for comparison" notes that no longer applied).
- Left historical mentions of the v1 filenames alone (the archived price-agent
  synthesis review and a frozen evaluation-results snapshot both name the
  prompt version that was actually in effect for that record at the time).

**Why:** a prompt file nothing loads, and a docstring pointing at it as if it
were live, is exactly the kind of drift this cleanup pass was trying to catch.

**Verified:** full suite passed with both files removed (confirmed no code or
live documentation reference remained).

---

## 2026-10-31 — Added a clarification step and a structured answered/unanswered breakdown

**Status:** implementation committed in `adc122f`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Added `needs_clarification`/`clarifying_question` to the router's routing
  record (rule R7): the router asks one short, specific question instead of
  guessing when a question is genuinely too unclear to route — not merely
  broad, vague on timing, or otherwise answerable with a best guess.
  `safe_route()` now forces `route=none` and clears `check_premise`/
  `answerable` whenever it's set; `tasks_for_route()` independently refuses to
  select any agent in that case too, so a caller that bypasses `safe_route()`'s
  repair still can't accidentally gather evidence before the question is
  resolved.
- `synthesise()` short-circuits on `needs_clarification` before any model call
  or evidence gathering, returning the clarifying question as the answer with
  `declined=True`.
- Added a structured `cannot_answer` list (`{part, reason}`) to the synthesis
  output (rule A9), alongside the existing declined flag and prose
  explanation, for every decline path: a full scope miss, a partial answer on
  a mixed question, and the new clarification case. `format_answer()` and the
  Streamlit UI (`ui/app.py`) render it as its own "Can't answer" section/
  callout instead of leaving it folded into the answer prose.

**Why:** for a policy question, the user should see plainly what was answered,
what wasn't, and why — not have to read it out of a paragraph — and the
system should ask back rather than guess when the question itself is unclear.

**Verified:** 98 offline tests passed across routing checks, synthesis, the
sequential pipeline and the P3 graph, including that neither agent nor the
model is called when a question needs clarification. No live model
classification was tested.

---

## 2026-10-31 — Refreshed current documentation against code and configuration

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Corrected decomposition defaults in the pipeline map, supervisor guide,
  ablation guide and root README: the current config selects baseline A;
  callers can enable focused tasks and the paired evaluator runs both variants.
- Updated routing/synthesis diagrams for clarification and deterministic scope
  responses, documented current return fields and report modules, and corrected
  the graph map so self-check runs before the final answer is returned.
- Documented persisted chunk fields versus normalized evidence, capture-date
  limits, candidate preservation and what policy abstention can establish.
  Marked historical synthesis findings and P5 pilot scores as historical rather
  than current independently verified results.
- Updated stage-review instructions for the saved six-question development
  batch, unverified references, compact workbook and separate judge costs.
  New command examples use a fresh batch name instead of reusing saved outputs.
- Fixed the broken historical report link, clarified optional dependencies and
  the actual folder layout, and added a documentation ownership/update checklist
  to [MAINTENANCE.md](MAINTENANCE.md).
- Aligned the current guides across pipeline overview, supervisor operation,
  batch/stage evaluation, policy RAG, chunk handoff, judge validation and team
  maintenance. Kept the root README consistent with those guides and labelled
  the older price/synthesis review as an archive.

**Why:** current guides should match executable behavior, distinguish saved
results from current settings, and give the team a repeatable way to update
documentation alongside future changes.

**Verified:** all 118 local links and their heading anchors passed the audit;
12 documented CLI help commands passed. Checked current config, chunk schema
and saved-run counts, and ran whitespace/diff checks. No pipeline or judge
inference was run.

---

## 2026-10-31 — Allowed explicitly disclosed nearby-area price estimates

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Added R8 to the active supervisor prompt: historical resale-price requests
  may use a supported containing/nearby town as an approximate geographic proxy
  when exact-location figures are unavailable and the location relationship can
  be established reliably. Added a routing example and an explicit R5 exception.
- Aligned decomposition, synthesis and self-check instructions: preserve the
  requested place, name the proxy area, retain flat type/period and transaction
  count, and clearly label the estimate. Exact-address requests remain unanswered
  when only nearby context is available; unknown geography must not be guessed.
- Updated the supervisor guide. This prompt change does not add geocoding or a
  distance-search tool; claims such as "closest" or "within 1 km" still require
  supporting location information. Prices must come from actual agent results.

**Why:** useful area-level price context should be available with clear limits
instead of silently substituting another area or presenting a proxy as exact.

**Verified:** 93 offline tests passed across routing, synthesis, decomposition,
price agents and graph integration. No live location matching or model calls
were run, and no price estimates were fabricated for verification.

---

## 2026-10-31 — Reduced stage-review sheets and added agent-question breakdowns

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Reduced the stage-review workbook from five sheets to Summary, Review and
  Agentic Details. Merged routing/evidence checks and optional judge context
  into Review; kept usage with the agent breakdown instead of a separate tab.
  Omitted the details sheet when no tasks or usage were recorded.
- Added the original question, actual focused agent questions, required answer
  elements, task IDs, attempts, decisions/reasons, follow-up policy searches,
  evidence IDs, errors and timing. Preserved baseline unsplit inputs and separate
  retries; missing historical details remain unknown rather than inferred.
- Linked summary human-grade counts and correctness means to the editable
  Review cells. Stage-cost summaries now use saved manifest pricing.
- Regenerated the existing review workbook from saved results without rerunning
  inference or judge calls, retaining all 12 executions and 22 agent attempts.

**Why:** fewer tabs make the report easier to present, while the focused-query
table shows what the agentic workflow actually asked each agent to resolve.

**Verified:** 36 export/diagnostic tests passed, covering merged judge/check
data, preserved usage totals, focused questions, retries, unknown evidence,
optional sheets and linked summary formulas. Visually checked all three sheets.

---

## 2026-10-31 — Removed MLflow and retained local evaluation reports

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Removed the tracking client, batch lifecycle hooks, grade publishing, CLI
  flags, configuration, pinned dependency and dedicated setup guide. Deleted
  the local tracking database/artifact directory and uninstalled all three
  tracking packages from the project environment. No tracking server was running.
- Moved reusable configuration/provenance helpers into `experiment_metadata.py`.
  Kept paired evaluation, local CPU/memory measurements, grading, comparison,
  Excel export, tabular reports and CSV question/usage history working locally.
  The sampling interval now lives under `experiment_measurements` in config.
- Replaced service-specific tests with local batch/metadata regression tests
  and updated documentation and the consolidated test runner.
- Removed retired tracking metadata from the saved evaluation manifest and
  recorded its previous hash and an explicit cleanup note. Updated the linked
  diagnostic manifest hash; question answers, evidence and usage records were
  preserved. Removed the obsolete integration changelog entry and ignore rules.

**Why:** simplify the project around local evaluation and presentation reports
without requiring a separate experiment-tracking service.

**Verified:** 195 offline tests passed with the tracking packages uninstalled,
covering batch execution, configuration drift, failed-run usage retention,
grading, Excel exports, supervisor/P3, diagnostics and CSV logging. Batch CLI
dry-run and diff checks passed. No model API calls were made.

---

## 2026-10-31 — Consolidated the routing practice questions

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Merged five unique P1 questions into `data/labels/practice_routing.csv`,
  producing one active CSV with 59 unique question IDs and question texts.
  Preserved the original 54 rows and all current labels. Folded P1's separate
  premise explanations into `rationale` to retain the existing nine-column schema.
- Removed the merged `practice_routing_P1.csv` and the empty, outdated
  `routing_labels.csv` placeholder. Updated the supervisor guide to use the
  consolidated dataset and keep new held-out questions separate from practice.
- Refreshed `data/labels/Questionaire.xlsx` from the consolidated CSV using
  Python, as explicitly requested. The workbook now contains the same 59
  questions and nine current fields, replacing the outdated labels and IDs in
  the previous review copy. Added wrapped text, row filters, frozen headers/IDs,
  label validation and a source-CSV hash. The CSV remains the evaluation input;
  workbook edits are not automatically synced back.

**Why:** a single active practice dataset avoids scattered questions and
outdated schemas without changing the evaluation scripts' default input path.

**Verified:** checked that all original rows survived unchanged, all five P1
questions and their explanations were retained, and no duplicate IDs or question
texts were introduced. Six routing-evaluation tests passed. Read back all 59
Excel rows and nine fields and compared them exactly against the CSV; checked
the table/filter range and frozen header, and visually inspected the workbook.
No model calls ran.

---

## 2026-10-31 — Removed the obsolete routing-label history folder

**Status:** uncommitted

**Who:** Kay, Cooper and Ed

- Deleted the archived routing-label CSV and its empty `data/labels/history/`
  folder. Updated the supervisor guide to refer to Git history for previous
  labels and question-ID mappings.

**Why:** the archive was not used by the app or evaluation scripts, and Git
already preserves its historical contents. Active routing labels remain in
`data/labels/practice_routing.csv`.

**Verified:** checked that the folder was removed and no active documentation
links to the deleted archive remain.

---

## 2026-10-31 — Added tabular evaluation reports for presentation

**Status:** implementation committed in `adc122f`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Added automatic `report.md` output when preparing stage review and a
  Markdown report alongside the reviewed JSON summary.
- Presented variant/category summaries, per-question stage checks, answer
  quality, diagnostic counts, reviewer findings and recommended fixes in
  separate tables. Kept full questions and answers in their own table.
- Displayed scored/total execution counts and distinguished pending review,
  unknown checks, N/A and zero scores. Escaped question/answer text so pipes,
  newlines and markup cannot break the tables. Existing reports are preserved.

**Why:** the team needs readable tables for presenting what worked, what
failed and what to improve, while retaining the detailed JSON for analysis.

**Verified:** 21 diagnostic tests passed, including presentation tables,
score denominators, reviewer comments, text escaping and output preservation.
No live question-list results have been generated.

---

## 2026-10-31 — Added question-list evaluation and stage failure diagnosis

**Status:** implementation committed in `adc122f`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Added `agents.supervisor.diagnostics` with offline commands to prepare
  reviewer references, diagnose saved batch runs and summarise reviewed scores.
- Separated routing, corpus evidence availability, retrieval, evidence
  selection, faithfulness, correctness, completeness and appropriate abstention.
  References remain separate from inference, and unverified fields stay unknown.
- Preserved policy retrieval candidates separately from passages supplied to
  synthesis, including candidates later rejected during abstention. This makes
  it possible to distinguish retrieval misses from evidence-selection issues.
- Added per-execution reviewer fields for what went well, what went wrong
  and recommended fixes, plus overall/per-category metrics and denominators.
  Failed executions remain in the review; missing grades remain pending.
- Checked reference-question identity, available corpus fingerprints, complete
  batch schedules, review IDs and score ranges. Added the
  [stage evaluation guide](stage_evaluation.md) and linked the existing batch guide.

**Why:** a poor answer alone does not reveal whether the problem was routing,
missing corpus coverage, retrieval, the evidence gate or answer generation.
Matching a reference chunk is a diagnostic observation, not proof of a correct
or faithful answer; independent review is still required.

**Verified:** the offline regression run passed 150 tests across diagnostics,
policy retrieval, usage logging, synthesis, supervisor/P3 and experiment tracking.
The team will provide a new question list; no live batch or quality improvement
is claimed by this implementation.

---

## 2026-10-31 — Captured policy abstention decisions in logs

**Status:** implementation committed in `adc122f`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Recorded policy decisions and reasons in the shared agent step log for both
  the sequential supervisor and P3 graph.
- Added `policy_abstained`, `policy_outcomes` and `answer_declined` to the run
  summary CSV. Outcomes include task IDs and attempts, preserving abstentions
  before successful retries, even when no policy model usage was reported.
- Kept policy abstention separate from final-answer decline and execution
  errors. Added an atomic upgrade for the known previous CSV header, retaining
  history and leaving historical outcome fields blank where values are unknown.
- Updated the [usage logging guide](usage_logging.md).

**Why:** the policy agent already returned `ABSTAIN` and its reason, but those
details were missing from the shared step and consumption logs. A completed run
can legitimately abstain on policy while retaining supported price results.

**Verified:** 111 tests passed across logging, supervisor/P3, decomposition and
experiment tracking, including abstention without model usage, retry history,
saved-trace outcomes and CSV history preservation.

---

## 2026-10-31 — Clarified refusals and supported topics for irrelevant questions

**Status:** implementation committed in `adc122f`; changelog entry uncommitted

**Who:** Kay, Cooper and Ed

- Added a consistent refusal for route `none`, explaining that the available
  sources cover HDB resale transactions and HDB/CPF housing policies, and
  listing the supported question areas without a synthesis model call.
- Updated routing, decomposition and synthesis instructions to filter unrelated
  content, preserve relevant housing conditions and answer supported parts of
  mixed requests while briefly declining unsupported parts.
- Included the routing reason in synthesis context and aligned the graph's
  self-check instructions with mixed-request handling.

**Why:** irrelevant requests should receive a clear limitation and useful
direction, while unrelated content in a mixed request should not prevent the
system from answering its supported housing parts.

**Verified:** 115 offline tests passed across synthesis, routing, supervisor/P3
and decomposition. Tests verified that requests routed to `none` skip retrieval
and synthesis model calls. Live model classification was not tested.

---

## 2026-10-31 — Removed generated reports; merged routing evaluation results

**Status:** committed in `3d87546` and `b20160e`

**Who:** Kay, Cooper and Ed

- Deleted the `reports/` directory (20 files): chunking, cleaning,
  deduplication, embedding and routing reports generated by scripts in
  `scripts/`. These were regenerable pipeline outputs, not inputs consumed
  by the model or app, so nothing else needed to change.
- Merged the four timestamped CSVs in `evaluation/results/` (two v1 runs,
  two v2 runs of the routing supervisor evaluation) into one
  `routing_supervisor_results_merged.csv`, adding `version`, `timestamp`
  and `source_file` columns. v1's `false_belief_label`/`false_belief_router`
  columns were renamed to v2's `check_premise_label`/`check_premise_router`
  on the way in, since they're the same field under its old and new name
  (see the 2026-10-25 "false beliefs" entry below for why the field was
  renamed). The existing `_summary.md` write-up for one of the v1 runs was
  left as is.

**Why:** both directories had accumulated run-to-run output clutter with
nothing in the codebase reading the files back, so they were safe to clean
up; keeping one merged results CSV instead of four separate ones makes it
possible to compare runs across prompt versions without juggling files.

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
- Updated `README.md`, `supervisor_guide.md` and `supervisor_ablation.md`
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

Added the historical `reports/routing_report.md` (removed with generated
reports on 31 October 2026), summarizing
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
  `premise_rationale` at that stage. Later cleanup separated the historical
  labels from the active file, which now has nine columns. The separate archive
  was removed on 31 October 2026; previous labels remain available in Git history.
  Drafted labels: 12 premises, 5 known false, 1 known true, 6 to verify.
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
of [the supervisor guide](supervisor_guide.md#agent-configuration-and-integration).

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

Rewrote `Docs/supervisor_guide.md` from scratch in plain English (the
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
after the fact — see `Docs/supervisor_guide.md` for the full detail.

- `router.py` / `synthesis.py` / `pipeline.py`: added a shared `usage_log`
  so every model call's token counts are recorded on the bundle
  (`bundle["usage"]`), for cost tracking.
- Added `agents/supervisor/score_answers.py` and
  `tests/test_supervisor_score_answers.py`: the run → grade → score
  workflow for scoring final answers on honesty and myth-acceptance,
  separate from `evaluate.py`'s routing-only scoring.
