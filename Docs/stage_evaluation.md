# Question-list evaluation and failure diagnosis

Use the team's new question list to assess the complete answer and trace what
went well or failed at each stage. No new question list has been supplied yet.
The tools below prepare references and review saved runs without calling models.

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

Generate a separate reviewer reference file:

```sh
python -m agents.supervisor.diagnostics template path/to/new_questions.csv --out path/to/references.json
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
python -m agents.supervisor.ablation run path/to/new_questions.csv --pipeline graph --out evaluation/ablation/new_questions_v1 --today 2026-10-31 --repeats 1 --dry-run
```

The dry run validates the input and schedule. Remove `--dry-run` to execute the
experiment once the question list and references are ready. One repeat means two
pipeline executions per question (A and B), each potentially making multiple
model calls. Use a fresh directory for each experiment and report repeats
separately from unique question count. The current work has not executed a live
question-list experiment.

After inference, prepare the diagnostic report:

```sh
python -m agents.supervisor.diagnostics prepare evaluation/ablation/new_questions_v1 --references path/to/references.json --chunks data/processed/chunks.jsonl --out evaluation/ablation/new_questions_v1/stage_review
```

The command produces:

- `report.md`: a presentation report with tables for variant/category results,
  stage checks by execution, answer-quality scores, diagnostic counts, reviewer
  findings and recommended fixes, followed by the questions and answers.
- `diagnostics.json`: per-run routes, verified reference fields, candidate and
  supplied policy passages, policy decisions/reasons/trace, price results,
  abstention flags and diagnostic observations. It records the input-file hashes.
- `review.csv`: one row per execution with blank quality scores and fields for
  what went well, what went wrong, the recommended fix and reviewer notes.

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

Save a reviewed copy of `review.csv`, then summarise:

```sh
python -m agents.supervisor.diagnostics summarise evaluation/ablation/new_questions_v1/stage_review/diagnostics.json path/to/reviewed.csv --out evaluation/ablation/new_questions_v1/stage_review/summary.json
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
