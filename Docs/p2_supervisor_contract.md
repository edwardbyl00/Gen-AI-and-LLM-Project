# P2 Supervisor Contract

Owner: P2 (supervisor and synthesis integration)
Status: published by P2. Teammates build their parts autonomously; this file
states what the supervisor produces and what it expects from others, so the
parts join cleanly. Full routing rules: `Docs/routing_spec.md`.

---

## A1. What the supervisor outputs

The supervisor reads the user's question and writes one routing record into
the shared state.

| Field | Type | Allowed values | Notes |
| ----- | ---- | -------------- | ----- |
| `route` | string | `price` / `policy` / `both` / `none` | Which agents to call |
| `false_belief` | bool | `true` / `false` | Question rests on something untrue; synthesis must correct it first |
| `answerable` | bool | `true` / `false` | Whether the actual question can be answered; `false` means "I don't know" or a decline, with context where useful |
| `reason` | string | one sentence | Cites a rule (R1 to R5) where one applies; written to the step log |

Notes for whoever builds the graph (P3):
- There is no separate "myth" or "unsure" route. A myth is `false_belief =
  true`; "unsure" is `answerable = false`.
- Invalid combinations are fixed by the supervisor before the record is
  written (routing spec, section 4), so downstream code can trust it.

## A2. Framework, model and settings

- **The router is a plain Python function**, independent of any agent
  framework: `route_question(question) -> dict` returning the record above.
  Whatever framework the graph uses, it wraps this function in a node.
- **Model, temperature and seed are read from `config.yaml`**, never typed
  into code (team rule in `Docs/MAINTENANCE.md`). `config.yaml` is currently
  empty on every branch; the router will read these keys:

  ```yaml
  llm:
    model: "<to be fixed by the team>"
    temperature: 0
    seed: 42
  ```

- The same model must be used across V0, V1 and V2 for a fair comparison.
- Observed: `src/llm_judge.py` on the `kay` branch sets `MODEL = "gpt-5.4"`
  in code. Suggest moving the judge model into `config.yaml` under its own
  key (e.g. `judge.model`) so it is fixed in one place.

## A3. Question IDs

- Format: `{set}_{author}_{number}`, e.g. `PR_P2_03` (practice), `HO_P4_11`
  (held out). The question kind goes in its own column, never in the ID,
  so relabelling a question never changes its ID.
- Routing labels live in `data/labels/routing_labels.csv`, keyed by
  `question_id`.
- Observed: `evaluation/ground_truth_40q.csv` (P4) uses IDs like `H01`,
  which are also document IDs in the corpus. Suggest prefixing them when
  merged into the shared question set, to avoid confusing the two.

## A4. What the supervisor passes to each agent, and expects back

The supervisor passes the user's question unchanged, plus today's date for
effective date filtering. It does not extract towns, flat types or periods;
that is the price agent's job (one job, one owner).

### Policy agent (P5, built on P4's index)

Observed on the `kay` branch, `src/policy_retriever.py`:

```
retrieve_policy_evidence(question, query_date=None, top_k=3) -> {
    "question", "query_date", "final_query", "requeried",
    "rewrite_accepted",
    "evidence": [ { "document_id", "chunk_id", "title", "source",
                    "category", "url", "effective_date", "text",
                    "section_title", "section_path", "score" } ]
}
```

The supervisor uses this as is. Synthesis needs `url` and `effective_date`
on every evidence item to cite sources with dates.

### Price agent (P1)

Not yet on GitHub. The supervisor expects:

```
price_agent(question, query_date) -> {
    "town", "flat_type", "period_start", "period_end",
    "median_price", "n_deals", "data_as_of"
}
```

`period_start` and `period_end` let synthesis state the exact period used
(routing spec, R2). `n_deals` lets synthesis warn when few deals exist.

### Adapters and stand-ins

- Each agent is called through a small adapter on the P2 side that converts
  its output into the shape above. If an agent's output changes, only the
  adapter changes, not the router or synthesis.
- Until an agent is ready, the supervisor uses a stand-in that returns fake
  data in the same shape, so routing can be built and tested now.

---

## Questions for teammates

- **P1:** what does the price agent take "recently" to mean by default
  (e.g. the latest 12 months of data)? Is the expected output shape above
  workable?
- **P4/P5:** does the corpus contain any announced CPF or HDB changes with a
  future effective date?
- **P4:** are the 40 questions in `ground_truth_40q.csv` part of the shared
  held out set? If so, P2 will not use them while tuning the router.

## To test during Phase E (P2 only)

- For myth questions, compare passing the raw question to the policy agent
  against passing a neutral rewording (e.g. "Can CPF savings be used for
  resale flats?"). Myth wording may pull up the wrong passages. If the
  neutral version is clearly better, the router gains an optional
  `policy_query` field.
