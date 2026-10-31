# Evaluation walkthrough

A plain, step-by-step guide to running a question-list evaluation end to
end: write questions, run the pipeline, get LLM judge scores, review, and
export a report. For the deeper technical reference on each step, see
[stage_evaluation.md](stage_evaluation.md) (diagnostics) and
[supervisor_ablation.md](supervisor_ablation.md) (the A/B ablation runner).
This page just gets you from "I have some questions" to "I have a
reviewable report" without needing to read either of those first.

All commands below assume you're in the project root with the virtual
environment active. If you haven't set that up yet, see
[README.md](../README.md#environment).

## The six steps, at a glance

```text
1. Write your questions           -> a CSV
2. Generate the reference template -> a JSON file to fill in by hand
3. Run the batch                   -> runs.jsonl, efficiency, cost, LLM judge scores
4. Prepare the diagnostic report   -> stage_review/ (routing, retrieval, faithfulness checks)
5. Export to Excel                 -> one spreadsheet to review in
6. (Optional) Score against your filled-in references -> the gated judge
```

Steps 1–2 are one-time setup per question list. Step 3 costs money (it
calls the model). Steps 4–5 are free and local. Step 6 is optional and only
works once you've filled in step 2 by hand.

---

## Step 1 — Write your questions

Copy the template and replace the example rows with your real questions.
Give the batch a short name — this walkthrough uses `my_batch`.

```sh
mkdir -p evaluation/ablation
cp evaluation/templates/unseen_evaluation_questions.template.csv \
   evaluation/ablation/my_batch_questions.csv
```

Open `evaluation/ablation/my_batch_questions.csv` and edit it. Each row needs:

| Column | Required? | What goes here |
| --- | --- | --- |
| `question_id` | Yes | A short unique label, e.g. `Q1`, `Q2` |
| `question` | Yes | The actual question text |
| `category` | No, but recommended | One of: `price`, `policy`, `mixed`, `false_premise`, `irrelevant`, `missing_evidence`, `missing_user_information`, `dataset_boundary` |

Keep hard or tricky questions in the list — don't filter them out. They're
exactly what this evaluation is for.

> **Common mistake:** forgetting to delete the `EXAMPLE_*` rows the
> template ships with. If you run a batch and later find every answer looks
> like it's about Tampines resale flats or the weather, you ran it against
> the unedited template.

## Step 2 — Generate the reference template

This creates one JSON entry per question, for a reviewer to fill in by hand
later (the correct route, a reference answer, etc.). It does **not** call a
model — it's just scaffolding.

```sh
python -m agents.supervisor.diagnostics template \
    evaluation/ablation/my_batch_questions.csv \
    --out evaluation/ablation/my_batch_references.json
```

You can fill this in now or after step 3 — the batch run doesn't need it.
But nothing in steps 4–6 that depends on a *verified* reference will work
until someone does. See [Filling in references](#filling-in-references) below.

## Step 3 — Run the batch

This is the paid step: it calls the model once per question per A/B variant
(and once more per question for the automatic LLM judge pass described
below).

```sh
python -m agents.supervisor.ablation run \
    evaluation/ablation/my_batch_questions.csv \
    --pipeline graph \
    --out evaluation/ablation/my_batch \
    --today 2026-10-31 \
    --repeats 1 \
    --dry-run
```

`--dry-run` just validates the input and prints what *would* run — no API
calls, no cost. Check the numbers look right (question count, variant
list), then drop `--dry-run` to actually execute:

```sh
python -m agents.supervisor.ablation run \
    evaluation/ablation/my_batch_questions.csv \
    --pipeline graph \
    --out evaluation/ablation/my_batch \
    --today 2026-10-31 \
    --repeats 1
```

This writes `evaluation/ablation/my_batch/` with `runs.jsonl`, `manifest.json`,
`efficiency.json`, `comparison.csv` and a blinded grading sheet. It also
**automatically runs an LLM judge pass** at the end and writes
`evaluation/ablation/my_batch_llm_judge_scores.json`. This judge doesn't
need your reference file — it scores faithfulness to the evidence the
pipeline actually retrieved, as a fast first read. (Pass `--no-judge` to
skip this if you don't want the extra model calls right now.)

> **Important:** `--out` must not already exist — the runner creates it
> fresh. If you need to re-run, pick a new name or delete the old directory
> first.

## Step 4 — Prepare the diagnostic report

This is free and local — it reads what step 3 saved and checks routing,
retrieval and evidence selection against your reference file (if filled in).

```sh
python -m agents.supervisor.diagnostics prepare \
    evaluation/ablation/my_batch \
    --references evaluation/ablation/my_batch_references.json \
    --chunks data/processed/chunks.jsonl \
    --out evaluation/ablation/my_batch/stage_review
```

This writes `stage_review/review.csv`, `stage_review/diagnostics.json` and
`stage_review/report.md`. If your references aren't filled in yet, this
still works — you just won't get routing/correctness checks, only what the
run itself recorded.

## Step 5 — Export to Excel

This bundles the review CSV, diagnostics and the LLM judge scores from
step 3 into one spreadsheet, so a reviewer doesn't need to open three files.

```sh
python -m agents.supervisor.diagnostics export-excel \
    evaluation/ablation/my_batch/stage_review \
    --llm-judge-scores evaluation/ablation/my_batch_llm_judge_scores.json \
    --out evaluation/ablation/my_batch/stage_review/review.xlsx
```

> **If this fails with `ModuleNotFoundError: No module named 'xlsxwriter'`:**
> your environment predates `requirements.txt` pulling in
> `requirements-experiments.txt`. Refresh it:
> ```sh
> pip install -r requirements.txt
> ```

Open `review.xlsx` and grade each row using the 0 / 0.5 / 1 anchors described
in [stage_evaluation.md](stage_evaluation.md#review-and-report).

## Step 6 — (Optional) Score against your verified references

This is the stricter, gated judge. It only scores a row once a human has
actually filled in and verified its reference — if nothing's filled in yet,
every row is skipped, which is expected, not a bug.

First, fill in `evaluation/ablation/my_batch_references.json` by hand for at
least some questions: set `ground_truth_verified: true`, and fill in
`expected_route`, `coverage_status`, `relevant_chunk_ids` and
`reference_answer`. Then:

```sh
python -m agents.supervisor.judge_tools prepass \
    evaluation/ablation/my_batch \
    --references evaluation/ablation/my_batch_references.json \
    --out evaluation/ablation/my_batch_judge_scores.json
```

The output tells you how many rows it judged vs. skipped, and why. A row is
only eligible once it's `ground_truth_verified: true`, has a known
`coverage_status`, routed to `policy`, and ran without an execution error.

---

## Filling in references

Open `evaluation/ablation/my_batch_references.json`. For each question,
a reviewer fills in:

| Field | What it means |
| --- | --- |
| `ground_truth_verified` | Set to `true` once you've checked the fields below yourself. Leave `false` until then — it's the gate that keeps unverified guesses out of the scored result. |
| `expected_route` | `price`, `policy`, `both`, or `none` — where the question *should* route. |
| `coverage_status` | Whether the frozen corpus actually supports answering this, e.g. `COVERED` or `NOT_COVERED`. |
| `relevant_chunk_ids` | The exact corpus chunk IDs that support the answer, if policy-related. |
| `reference_answer` | A short, correct answer you'd grade against. |
| `required_conditions` | Any conditions the answer must mention to be complete. |

Leave `ground_truth_verified` as `false` for anything you haven't actually
checked — a wrong "verified" reference is worse than an honest blank one.

## Troubleshooting

**"Judged 0/N executions; skipped N."**
Every row needs a verified reference to pass the gate in step 6. Check
`ground_truth_verified` is `true` and `coverage_status` isn't `UNKNOWN` in
your references file. If you just want a quick first read without filling
anything in, use the automatic judge from step 3 instead
(`my_batch_llm_judge_scores.json`) — see
[stage_evaluation.md](stage_evaluation.md#alternative-judge-without-verified-references).

**`ModuleNotFoundError: No module named 'xlsxwriter'`**
Run `pip install -r requirements.txt` to refresh your environment —
`requirements.txt` includes `requirements-experiments.txt` (Excel export,
local CPU/memory measurement).

**`FileExistsError` or the run errors because `--out` already exists**
The ablation runner refuses to overwrite an existing directory. Pick a new
`--out` name, or delete/rename the old one first if you're intentionally
redoing it.

**My answers all look like they're about Tampines / the weather**
You ran the batch against the unedited example template instead of your
real questions file — see the callout in [Step 1](#step-1--write-your-questions).

**Push rejected with "tip of your current branch is behind"**
Not a diagnostics issue — someone else pushed to the same branch. Run
`git fetch`, then `git merge origin/<branch>` and resolve any conflicts
before pushing again.
