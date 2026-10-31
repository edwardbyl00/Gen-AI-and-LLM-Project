# Question-list evaluation and failure diagnosis

Use a question list to assess the complete answer and trace what went well or
failed at each stage. Checked on 31 October 2026: the saved `new_questions_v1`
development batch contains six unique questions and 12 graph executions across
A and B, with 22 recorded agent attempts. Its references are still unverified,
so it does not establish routing accuracy, retrieval recall or correctness.

The saved manifest records that batch's actual questions and settings; mutable
input CSVs and current prompts may have changed since inference. The compact
review workbook is at
`evaluation/ablation/new_questions_v1/compact_review/review.xlsx`.
It is a generated local artifact and may not exist in a fresh clone.

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
`--out` below is created fresh by the
batch runner in the next step and must not already exist, so keep the
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
model calls. Use a fresh directory for each experiment and report repeats
separately from unique question count. The commands below illustrate a fresh
batch; do not overwrite the saved development batch to rerun changed prompts.

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
python -m agents.supervisor.diagnostics prepare evaluation/ablation/team_questions_v2 --references evaluation/ablation/team_questions_v2_references.json --chunks data/processed/chunks.jsonl --judge-scores evaluation/ablation/team_questions_v2_judge_scores.json --out evaluation/ablation/team_questions_v2/stage_review
```

Drop `--judge-scores` to produce the same report with every row shown as "Not
judged" — the rest of the workflow, including `summarise`, is unaffected
either way; the judge's score is never read back into `GRADES` or any scored
metric, only displayed.

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
python -m agents.supervisor.diagnostics export-excel evaluation/ablation/team_questions_v2/stage_review \
    --llm-judge-scores evaluation/ablation/team_questions_v2_llm_judge_scores.json \
    --out evaluation/ablation/team_questions_v2/stage_review/review.xlsx
```

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
