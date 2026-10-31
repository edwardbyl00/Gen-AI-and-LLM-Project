# Validating the LLM-as-judge

`scripts/evaluate_agentic_answers.py` scores every pilot answer with
`src/ground_truth_judge.py` (and optionally `src/llm_judge.py`). Neither judge
has been checked for bias or agreement with a human reviewer. This is that
check, via `scripts/validate_llm_judge.py`.

| Risk | What we check | Cost |
| --- | --- | --- |
| Evidence-order sensitivity | Re-judge the same (question, answer) pair with the retrieved evidence reversed; flag any score that moves | Paid (re-runs the judge) |
| Agreement with a human reviewer | Compare the judge's rubric scores against a reviewer's independent scores on a sample | Free (reads saved judge output) |

Both judges are pointwise: they score one system answer against a rubric and
the supplied evidence, not "answer A vs answer B". There is no literal
position to swap. The equivalent bias for a pointwise judge is whether the
*order* of the evidence passages changes the score — a judge that is actually
reading for content, not position, should be stable under reversal. This is
why the first check reverses evidence order rather than answer order.

## Prerequisite

Both checks read from an existing judged results file, so run the pilot once
first:

```sh
python scripts/evaluate_agentic_answers.py --judge
```

This writes `evaluation/agentic/agentic_vs_baseline_pilot_10q_judged.json`,
which both checks below load.

## Evidence-order sensitivity (`swap-check`)

```sh
python scripts/validate_llm_judge.py swap-check --n 5 --threshold 1
```

For each of the first `--n` (question, system) pairs in the judged results,
this calls `judge_against_ground_truth` twice: once with evidence in its
original order, once with the list reversed. A pair is flagged `UNSTABLE` if
the total score or any single rubric field moves by `--threshold` points or
more between the two calls.

This makes real, paid judge calls (two per pair), so start with a small `--n`.
Output goes to `evaluation/agentic/judge_swap_check.json`. A judge with a high
unstable rate is scoring position, not content, and its scores should not be
trusted at face value until the prompt or rubric is revised.

## Human agreement (`human-check`)

Two steps: emit a template, have a reviewer fill it in, then score it.

```sh
python scripts/validate_llm_judge.py human-check emit-template \
    --out evaluation/agentic/human_label_sample.csv
```

This writes one row per already-judged (question, system) pair, with the
judge's own scores in `judge_<field>` columns and blank `human_<field>`
columns (plus `human_total` and `human_notes`) for a reviewer to fill in. Use
the same 0/1/2 scale as the rubric in `src/ground_truth_judge.py`
(`answer_correctness`, `ground_truth_completeness`, `unsupported_claims`,
`appropriate_conditionality`, `appropriate_abstention`). A reviewer does not
need to see the judge's scores while grading; hide the `judge_*` columns if
blind grading is wanted.

Once filled in:

```sh
python scripts/validate_llm_judge.py human-check score \
    --labels evaluation/agentic/human_label_sample.csv
```

A row only counts if every `human_<field>` column is filled in; partially
graded rows are skipped and reported separately. This prints, per rubric
field, the exact-match rate and mean absolute error between judge and human
scores, then lists the worst total-score disagreements with the reviewer's
notes. It also writes `<labels>.summary.json` alongside the CSV.

There is no fixed pass/fail threshold here, since the pilot sample is small
(10 questions x 2 systems). Treat a low exact-match rate or a cluster of
large disagreements as a reason to revise the rubric or prompt in
`src/ground_truth_judge.py`, not as a final verdict on judge quality — scale
up the human sample before relying on this for a go/no-go decision.

## What this does not check

- Self-preference bias (the judge rating its own model family higher) is not
  tested here, since the project uses one fixed judge model
  (`judge.model` in `config.yaml`) throughout.
- Verbosity bias (preferring longer answers) is not isolated; a reviewer
  disagreement that correlates with answer length is a sign to check for it
  manually in `human_notes`.
- This validates the judge's *scoring*, not the underlying rubric's
  *coverage* — see [stage_evaluation.md](stage_evaluation.md) for the
  broader per-stage diagnostic review, including routing, retrieval and
  evidence-selection failures the judge rubric does not score directly.
