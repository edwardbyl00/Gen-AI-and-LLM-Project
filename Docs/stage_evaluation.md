# Evaluation guide

Use this guide to take a question list through a batch run, judge scoring,
stage diagnosis, human review and a final report. All commands assume you are
in the project root with the virtual environment active; see the
[environment setup](../README.md#environment).

## Copy-and-paste steps

Run these blocks in order in the **same terminal**, from the project root.
Steps 1–5 produce a review workbook. Step 6 produces the human-graded summary.
The detailed sections below explain the checks and optional reference-based judge.

Pick one shell and stick with it for the whole sequence — the variables set in
step 1 (`$QUESTIONS`, `$REFERENCES`, `$RUN`, `$REVIEW`) only exist in the
terminal session that set them.

### 1. Set the batch name and edit the questions

Change only `BATCH` and `QUERY_DATE` here when starting a different evaluation.
Existing question files are preserved.

**macOS / Linux (bash/zsh):**

```sh
source .venv/bin/activate
BATCH=team_questions_v2
QUERY_DATE=2026-10-31
QUESTIONS="evaluation/ablation/${BATCH}_questions.csv"
REFERENCES="evaluation/ablation/${BATCH}_references.json"
RUN="evaluation/ablation/${BATCH}"
mkdir -p evaluation/ablation
if [ ! -f "$QUESTIONS" ]; then
  cp evaluation/templates/unseen_evaluation_questions.template.csv "$QUESTIONS"
fi
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
$BATCH = "team_questions_v2"
$QUERY_DATE = "2026-10-31"
$QUESTIONS = "evaluation/ablation/${BATCH}_questions.csv"
$REFERENCES = "evaluation/ablation/${BATCH}_references.json"
$RUN = "evaluation/ablation/${BATCH}"
New-Item -ItemType Directory -Force -Path evaluation/ablation | Out-Null
if (-not (Test-Path $QUESTIONS)) {
  Copy-Item evaluation/templates/unseen_evaluation_questions.template.csv $QUESTIONS
}
```

**Stop here and edit the question CSV.** Keep the header
`question_id,question,category`; replace all `EXAMPLE_*` rows with your questions,
then save it. Do this before generating the references in step 2.

### 2. Generate matching references

This creates blank, **unverified** references for the questions you just saved.
An existing reference file is backed up first, including any human work in it.
If you already completed matching verified references, skip this block and keep
them. After editing questions, regenerate and review the affected references;
the IDs and question text must match the saved run.

**macOS / Linux (bash/zsh):**

```sh
if [ -f "$REFERENCES" ]; then
  mv "$REFERENCES" "${REFERENCES}.backup.$(date +%Y%m%d%H%M%S)"
fi
python -m agents.supervisor.diagnostics template "$QUESTIONS" --out "$REFERENCES"
```

**Windows (PowerShell):**

```powershell
if (Test-Path $REFERENCES) {
  Move-Item $REFERENCES "${REFERENCES}.backup.$(Get-Date -Format yyyyMMddHHmmss)"
}
python -m agents.supervisor.diagnostics template $QUESTIONS --out $REFERENCES
```

You can leave the new references unverified for a first diagnostic report.
Correctness and reference-based checks need independently verified references.

### 3. Run the evaluation

Validate first (no model calls):

**macOS / Linux (bash/zsh):**

```sh
python -m agents.supervisor.ablation run "$QUESTIONS" --pipeline graph --out "$RUN" --today "$QUERY_DATE" --repeats 1 --dry-run
```

**Windows (PowerShell):**

```powershell
python -m agents.supervisor.ablation run $QUESTIONS --pipeline graph --out $RUN --today $QUERY_DATE --repeats 1 --dry-run
```

Then run it (**paid model calls**, including the automatic evidence-based judge)
by dropping `--dry-run` from either command above.

Reusing `BATCH` overwrites generated run results and clears old reviews and
default judge scores. Change `BATCH` in step 1 to retain an earlier run.
Do not edit the questions between this step and report preparation.

### 4. Prepare the diagnostic report

This is local and makes no model calls. A timestamp gives each report a new
folder, so repeating this block does not overwrite human grades.

**macOS / Linux (bash/zsh):**

```sh
REVIEW="$RUN/stage_review_$(date +%Y%m%d%H%M%S)"
python -m agents.supervisor.diagnostics prepare "$RUN" --references "$REFERENCES" --chunks data/processed/chunks.jsonl --out "$REVIEW"
```

**Windows (PowerShell):**

```powershell
$REVIEW = "$RUN/stage_review_$(Get-Date -Format yyyyMMddHHmmss)"
python -m agents.supervisor.diagnostics prepare $RUN --references $REFERENCES --chunks data/processed/chunks.jsonl --out $REVIEW
```

### 5. Export the Excel workbook

**macOS / Linux (bash/zsh):**

```sh
python -m agents.supervisor.diagnostics export-excel "$REVIEW" --llm-judge-scores "${RUN}_llm_judge_scores.json" --out "$REVIEW/review.xlsx"
```

**Windows (PowerShell):**

```powershell
python -m agents.supervisor.diagnostics export-excel $REVIEW --llm-judge-scores "${RUN}_llm_judge_scores.json" --out "$REVIEW/review.xlsx"
```

Open `review.xlsx` in the folder created in step 4. If step 3 used `--no-judge`,
omit `--llm-judge-scores "${RUN}_llm_judge_scores.json"` from this command.
The workbook contains the results, stage details and judge scores; human grades
remain blank until reviewed.

### 6. Grade and summarise (when ready)

Fill the human grade columns in `$REVIEW/review.csv` using 0, 0.5, 1 or `NA`,
and add your findings. See [Review and report](#review-and-report) for the rubric.
If you graded in Excel, copy the grades and notes into `review.csv`; edited
workbooks are not imported automatically. Save the CSV, then run:

**macOS / Linux (bash/zsh):**

```sh
python -m agents.supervisor.diagnostics summarise "$REVIEW/diagnostics.json" "$REVIEW/review.csv" --out "$REVIEW/summary.json"
```

**Windows (PowerShell):**

```powershell
python -m agents.supervisor.diagnostics summarise "$REVIEW/diagnostics.json" "$REVIEW/review.csv" --out "$REVIEW/summary.json"
```

The final reports are `summary.json` and `summary.md` in the review folder.
Run this once per output name; to summarise revised grades, use a new name such
as `summary_v2.json`.

## Detailed reference

The sections below explain the same workflow, its optional judge pass and how
to interpret the results. They are reference material, not additional required
steps after the copy-and-paste sequence.

## What the evaluation checks

Use a question list to assess the complete answer and trace what went well or
failed at each stage. Unverified references do not establish routing accuracy,
retrieval recall or correctness — only a reviewer-verified reference does.

The saved manifest records a batch's actual questions and settings; mutable
input CSVs and current prompts may have changed since inference. The exported
review workbook lives at `evaluation/ablation/<BATCH>/stage_review_<timestamp>/review.xlsx`
(see [step 5](#5-export-the-excel-workbook)). It is a generated local artifact
and may not exist in a fresh clone.

Reference preparation, diagnostics, summary and report export are offline.
Pipeline inference and the optional judge passes make model calls; judge
passes are separate steps with their own costs.

| Area | What we check | Evidence for the assessment |
| --- | --- | --- |
| Routing | Did the supervisor choose price, policy, both or neither? Were all requested parts and constraints preserved in the tasks? | Independently agreed expected route, original question, routing reason and task trace |
| Evidence availability | Does the frozen corpus actually support the question, fully or partly? | Reviewer-verified passages, source dates and corpus chunk IDs; for prices, verified filters and statistics from the frozen transaction data |
| Retrieval | Did the policy agent retrieve the relevant passages, including conditions needed to answer? | Retrieved candidates compared with verified reference passages; reviewers assess relevance and sufficiency |
| Evidence selection | Did the assessor pass useful evidence to synthesis, or remove it and abstain? | Candidate passages, supplied passages, assessment trace, `ANSWER_READY`/`ABSTAIN` and reason |
| Faithfulness | Is each material claim supported by the evidence and price facts actually supplied to synthesis? | Claim-by-claim comparison with supplied passages and transaction results |
| Correctness | Is the answer factually right for the original question and fixed date? | Independent reference answer, required conditions, official source text and independently checked price statistics |
| Completeness and abstention | Were all supported parts answered and unsupported parts clearly declined? | Original question, verified coverage and final answer; distinguish missing user facts from missing policy evidence |

Faithfulness and correctness are different: an answer can accurately repeat an
irrelevant or outdated passage and still be wrong for the question. Conversely,
an answer that happens to be correct can be unfaithful if its claims have no
support in the supplied evidence. A citation or matching chunk ID does not by
itself establish either score.

## Prepare the new questions and references

Save the supplied list with unique `question_id`, `question` and optional
`category` columns. Use categories such as price, policy, mixed, false premise,
irrelevant, missing evidence, missing user information and dataset boundary.
Keep every question, including difficult cases and failures.

Copy the fill-in template and replace the example rows with the real list.
Delete all `EXAMPLE_*` rows before running; otherwise you will evaluate the
template questions rather than your own list.
`--out` below is created or reused by the
batch runner in the next step. Keep the
questions file and the generated references file one level up, in
`evaluation/ablation/` itself:

```sh
mkdir -p evaluation/ablation
cp evaluation/templates/unseen_evaluation_questions.template.csv evaluation/ablation/team_questions_v2_questions.csv
```

Generate a separate reviewer reference file:

```sh
python -m agents.supervisor.diagnostics template evaluation/ablation/team_questions_v2_questions.csv --out evaluation/ablation/team_questions_v2_references.json
```

For each question, the reviewer fills in the expected route, reference answer,
required conditions, source URLs and source/reference date. Verify policy
support against the frozen full corpus, not merely the search results returned
for the test question. Record `relevant_chunk_ids` and `coverage_status`:

- `FULL`: the policy corpus covers the requested policy facts.
- `PARTIAL`: only some requested policy facts are supported.
- `NOT_COVERED`: an independent corpus audit found no supporting policy evidence.
- `NOT_APPLICABLE`: no policy evidence is required, for example a price-only or
  irrelevant question. Verify price answers against the transaction snapshot.
- `UNKNOWN`: coverage has not yet been established.

Set `ground_truth_verified` to true only after checking the references and
expected route. It starts false; blank or unverified fields are never counted as
ground truth. `reference_as_of` records the date to which the reference applies.
An ID being present in `chunks.jsonl` verifies file presence, not semantic
support, policy currency, or presence in the vector index. Check those separately
when reviewing availability. Record the reference-file hash or commit it before
inference; the diagnostics report records its hash again for audit.

Freeze the questions, references, corpus, price snapshot, query date, code,
prompts, model and retrieval settings. Keep references out of inference. The
existing ablation loader passes only question text, date and variant into the
pipeline, ignoring reference columns. A reference file remains reviewer-only.

## Execute and prepare stage review

Use the existing [batch runner](supervisor_ablation.md). This example runs both
decomposition variants through the full graph and its current self-check loop:

```sh
python -m agents.supervisor.ablation run evaluation/ablation/team_questions_v2_questions.csv --pipeline graph --out evaluation/ablation/team_questions_v2 --today 2026-10-31 --repeats 1 --dry-run
```

The dry run validates the input and schedule. Remove `--dry-run` to execute the
experiment once the question list and references are ready. One repeat means two
pipeline executions per question (A and B), each potentially making multiple
model calls. Report repeats separately from unique question count. Reusing the
same `--out` reruns the whole batch and replaces the previous generated outputs;
use a different directory to compare experiments or changed prompts.

Run the validated batch:

```sh
python -m agents.supervisor.ablation run evaluation/ablation/team_questions_v2_questions.csv --pipeline graph --out evaluation/ablation/team_questions_v2 --today 2026-10-31 --repeats 1
```

This writes `runs.jsonl`, `manifest.json`, `efficiency.json`, `comparison.csv`
and a blinded grading sheet under the output directory. By default, it also
runs the evidence-based judge and writes
`evaluation/ablation/team_questions_v2_llm_judge_scores.json`. Use `--no-judge`
to skip those additional model calls. See
[judge without verified references](#alternative-judge-without-verified-references)
for what this score measures and how to rerun it.

## Judge-gated review: LLM-as-judge first, then human

After inference, optionally run the LLM-as-judge pre-pass before the diagnostic
report. This makes additional judge calls after pipeline inference;
`agents.supervisor.diagnostics` stays fully offline. It scores each verified,
policy-route execution with `src/ground_truth_judge.py`'s rubric and writes a
`judge_scores.json`:

```sh
python -m agents.supervisor.judge_tools prepass evaluation/ablation/team_questions_v2 --references evaluation/ablation/team_questions_v2_references.json --out evaluation/ablation/team_questions_v2_judge_scores.json
```

Unverified references, price-only or mixed price+policy routes, and failed
executions are skipped and listed under `skipped` in the output, since the
rubric was written to score a single policy answer, not a price result or a
mixed answer as a whole. Skipped rows simply show "Not judged" later; nothing
else about the review changes for them.

The judge's score and reason are **context for the reviewer, not a
replacement for independent grading**. They appear in `review.csv` as
`judge_total_score` / `judge_reason`, and in `report.md`'s answer-quality
table, both ahead of the still-blank human grade columns. Seeing the judge's
number before grading is a known anchoring risk: a reviewer who is unsure may
unconsciously drift toward the judge's score rather than forming an
independent one. If that risk matters more than the convenience, skip
`--judge-scores` below and grade blind instead, or compare a sample of grades
done with and without it visible.

Prepare the diagnostic report, with or without the pre-pass:

```sh
python -m agents.supervisor.diagnostics prepare evaluation/ablation/team_questions_v2 --references evaluation/ablation/team_questions_v2_references.json --chunks data/processed/chunks.jsonl --out evaluation/ablation/team_questions_v2/stage_review
```

If you ran the optional reference-based pre-pass, add
`--judge-scores evaluation/ablation/team_questions_v2_judge_scores.json`.
Without it, the reference-based judge fields show "Not judged". The rest of
the workflow, including `summarise`, is unaffected; the judge's score is never
read back into `GRADES` or any scored metric, only displayed. The automatic
evidence-based scores can be included separately during Excel export below.

Before relying on these scores, check that the judge itself is trustworthy —
see [llm_judge_validation.md](llm_judge_validation.md) for the evidence-order
and human-agreement checks that calibrate it.

The command produces:

- `report.md`: a presentation report with tables for variant/category results,
  stage checks by execution, answer-quality scores, diagnostic counts, reviewer
  findings and recommended fixes, followed by the questions and answers.
- `diagnostics.json`: per-run routes, verified reference fields, candidate and
  supplied policy passages, policy decisions/reasons/trace, price results,
  abstention flags and diagnostic observations. It records the input-file hashes.
- `review.csv`: one row per execution with blank quality scores and fields for
  what went well, what went wrong, the recommended fix and reviewer notes. If
  `--judge-scores` was supplied, `judge_total_score` and `judge_reason` are
  filled in next to the still-blank human grade columns; otherwise they are
  blank for every row.

When the saved manifest has the batch schedule, an incomplete or duplicated
schedule is rejected. Recorded execution failures remain in the review;
interrupted experiments must be completed as a fresh comparable run rather
than silently reporting only the completed subset.

The existing 40-question ground-truth CSV can also be read as a reference file,
but it has no expected-route column. Routing scores remain unknown until
reviewers supply verified expected routes. It is not a substitute for references
for the new unseen list.

If the inference manifest has a chunk hash, a different chunk snapshot is
rejected. Without `--chunks`, corpus-presence checks remain unknown. Old traces
without candidate capture cannot establish which passages the assessor removed;
candidate recall stays unknown rather than treating abstention as retrieval
failure. New traces preserve the candidates returned by retrieval, including
targeted policy subqueries, separately from passages supplied to synthesis.
These are not all possible search hits or the internal pre-filter rankings.

Automatic observations are diagnostic leads, not confirmed root causes:

- `routing_mismatch`: the observed route differs from the verified expected route.
- `reference_chunks_missing_from_snapshot`: a gold ID is absent from this file;
  check ingestion, corpus versions or stale reference IDs.
- `verified_corpus_gap`: the independent reviewer marked the policy request
  `NOT_COVERED`; an appropriate abstention can still be a good answer.
- `no_reference_chunk_retrieved`: verified reference chunks exist in the file,
  but none appears in captured policy candidates.
- `reference_candidates_not_supplied_to_synthesis`: a reference chunk was
  retrieved but no reference chunk survived selection for the answer writer.
- `execution_error`: a pipeline or agent error needs separate investigation.

Reference candidate and supplied recall measure exact overlap with the labeled
reference IDs, across the latest policy task results, rather than Recall@K or
all-attempt search recall. Labels may describe only core evidence, and alternative
valid evidence may exist. Review passages before assigning a retrieval or gate
failure. A partial set of reference hits does not prove sufficient evidence.
Review query constraints, task-level coverage and price-agent filters in the
full `runs.jsonl` bundles as well. Prior policy attempts remain in the step log;
the earlier usage-log flag also records abstentions before a successful retry.

### Alternative: judge without verified references

The gated `judge_tools prepass` above only scores rows with a verified
reference (`ground_truth_verified: true`), a known `coverage_status`, route
`policy`, and no execution error — by design, since its rubric
(`src/ground_truth_judge.py`) compares the answer against that reference.
Before any references are filled in, every row is skipped as
`not_eligible_for_ground_truth_judge`.

To get a first read before references are ready, `scripts/judge_ablation_answers.py`
scores every execution with an answer and policy evidence, regardless of
route, coverage or reference state, using the ungated faithfulness-style
judge (`src/llm_judge.py`, the same one used for the P5 pilot in
`scripts/evaluate_agentic_answers.py`). It rates `evidence_support`,
`policy_currency`, `citation_relevance`, `unsupported_claims` and
`appropriate_abstention` (0-2 each) against the evidence actually supplied
to synthesis, not against a reference answer.

**This now runs automatically** at the end of `agents.supervisor.ablation run`
(default `judge=True`), writing
`evaluation/ablation/<run-name>_llm_judge_scores.json` right after
`runs.jsonl` is written. Pass `--no-judge` to skip it (e.g. to avoid the
extra paid judge calls, or when references are already verified and you only
want the gated `prepass` scores). To run it by hand against an existing run
directory instead:

```sh
python -m scripts.judge_ablation_answers evaluation/ablation/team_questions_v2
```

This makes one real judge call per execution (paid) and writes
`evaluation/ablation/<run-name>_llm_judge_scores.json` (`--out` to choose a
different path), with one entry per `review_id` holding the rubric fields,
`reason`, token usage/cost and the question/variant/category. It is
separate from `review.csv` and from the gated `judge_scores.json`: it does
not fill in any blank grade column, and `diagnostics summarise` never reads
it. Treat it as a fast first read to compare against human grades later,
the way the pilot's judge-vs-human check works — and, per
[llm_judge_validation.md](llm_judge_validation.md), this judge has not been
validated for bias or human agreement either, so don't report its numbers
as the scored result.

## Review and report

Grade `evidence_relevance`, `faithfulness`, `correctness`, `completeness` and
`appropriate_abstention` independently, using the agreed 0/0.5/1 anchors:

| Score | Interpretation |
| --- | --- |
| 1 | Fully meets the criterion |
| 0.5 | Partly meets it, with a material gap |
| 0 | Does not meet it |
| blank | Pending review |
| NA | Not applicable; explain why in reviewer notes |

Evidence relevance concerns the captured candidates, including conditions needed
for the question, rather than whether any passage happens to mention housing.
Faithfulness concerns only supplied evidence and facts. Correctness concerns
the independent references. Assess each part of a mixed request. A justified
abstention can score fully for correctness and appropriate abstention; if no
factual claims or evidence are present, faithfulness or relevance may be NA.
Failed executions receive zero quality scores, rather than being excluded or
marked NA. Keep missing grades blank and explain ambiguous questions rather
than inventing a reference answer. Prefer a second reviewer and adjudication.

### Review in a spreadsheet

`review.csv` opens directly in Excel/Numbers, but for a formatted workbook
combining it with the stage checks and both judge-score files, build one
with `agents.supervisor.stage_review_excel` (also wired as
`agents.supervisor.diagnostics export-excel`); it never calls a model, only
reads what `prepare` and `judge_ablation_answers.py` already wrote:

```sh
python -m agents.supervisor.diagnostics export-excel evaluation/ablation/team_questions_v2/stage_review --llm-judge-scores evaluation/ablation/team_questions_v2_llm_judge_scores.json --out evaluation/ablation/team_questions_v2/stage_review/review.xlsx
```

(Written as one line deliberately — a `\`-continued multi-line version can
paste incorrectly in some terminals, see [Step 5](#5-export-the-excel-workbook)
for the same command built from shell variables.)

`--llm-judge-scores` is optional; omit it if that file doesn't exist yet.
The workbook has at most three sheets:

- **Summary**: opens first. Per variant/category — execution and question counts,
  human-graded count, mean correctness (`Pending` until `Review` is
  graded), `Policy ANSWER_READY`/`ABSTAIN` counts (a retrieval-success
  proxy that needs no verified reference), mean reference candidate/supplied
  recall (`Unknown` until references are verified), the ungated judge's
  mean total score, and token/cost totals. A second table, "Tokens by
  stage", sums reported usage across all executions, split by variant, using
  saved manifest pricing. Human-graded counts and mean correctness reference
  the Review cells through formulas, so they update when grades are edited.
- **Review**: one row per execution, combining the original question/answer,
  route, policy outcome, optional judge scores, the shaded human-grade columns
  and reviewer findings. Expand the grouped columns on the right for routing,
  coverage, recall, policy reasons, diagnostic flags and full judge details.
  No separate checks or judge sheets are created. Blank optional judge columns
  are omitted when no scores/errors are supplied.
- **Agentic Details**: created only when tasks or usage are recorded. Its first
  table shows the original question alongside each focused price/policy question,
  required answer elements, task ID, agent, execution attempt, decision/reason,
  recorded follow-up searches, evidence IDs, errors and duration. This makes the
  breakdown of agentic/decomposed questions explicit. Baseline runs show the
  original unsplit question; missing details are marked unknown/not recorded.
  Retries remain separate, and earlier attempts do not borrow later evidence.
  A second table retains each stage's calls and tokens, including router,
  synthesis and self-check, with a bold TOTAL row per execution. These totals
  are the saved execution totals, not additional calls to sum again.

Workbook edits are for review/presentation. To run `summarise`, transfer the human
grades and notes into the original `review.csv` while preserving its machine
column names and review IDs; the exporter does not import edited workbooks.

None of the correctness, candidate-recall or supplied-recall figures are
real scores yet on an unverified/ungraded run — they report what's
knowable right now, the same caveat as the rest of this doc.

Save a reviewed copy of `review.csv`, then summarise:

```sh
python -m agents.supervisor.diagnostics summarise evaluation/ablation/team_questions_v2/stage_review/diagnostics.json path/to/reviewed.csv --out evaluation/ablation/team_questions_v2/stage_review/summary.json
```

The report includes per-variant and per-category metrics, diagnostic-flag counts,
unique question counts, scored denominators, pending grades and NA counts.
Do not describe pending-review means as final accuracy, or repeats as independent
questions. Use the reviewer comments to name the failure stage and recommended
fix; flags alone do not prove causation. The stage review is for diagnosis, not
a blinded answer-quality comparison: its full traces expose the variant. Use
the batch runner's separate `grading_blind.csv` for independent blind grading.

The summary command also writes `summary.md` alongside `summary.json`, containing
the same presentation tables with the reviewed grades and comments filled in.
Open the Markdown report in a viewer to present or copy its tables. Its score
cells show the scored/total execution count; unknown checks, pending review and
N/A remain visibly distinct from a zero score. Full answers are in a separate
table so the stage and quality tables stay compact. Presentation exports make
no additional model calls. Existing reports are not overwritten.

The existing ablation rubric calls faithfulness `groundedness`; the new review
uses the explicit name `faithfulness`. Its `review.csv` has a separate schema
and should be summarised with this command, not passed directly to `ablation score`.

## Troubleshooting

**The reference-based judge skipped every row.** Check that the references have
`ground_truth_verified: true` and a known `coverage_status`. Only successful
policy-route executions qualify. Use the automatic evidence-based judge for a
first read while references are pending; its scores do not establish correctness.

**Excel export cannot import `xlsxwriter`.** Refresh the environment with
`python -m pip install -r requirements.txt`. This includes the experiment and
Excel export dependencies.

**I want to rerun the same batch.** Repeat the run command with the same `--out`.
It overwrites the generated run files, removes `stage_review`, `compact_review`
and custom review folders containing both `diagnostics.json` and `review.csv`,
and clears the default sibling judge-score files, including with `--no-judge`.
Regenerate diagnostics, judge scores and human grades for the new results.
Unrelated files and input CSVs are preserved. Custom judge/report files saved
elsewhere must be refreshed separately. Use a new `--out` to retain both runs.

**Answers seem unrelated to your questions.** Check the input CSV for leftover
`EXAMPLE_*` template rows and confirm the question path passed to the runner.

**Correctness is pending or recall is unknown.** Fill in and verify references,
then prepare diagnostics again in a fresh review directory. Correctness also
requires human grading; running a judge does not fill the human grade columns.
