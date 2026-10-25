# Change Log

A running record of what changed in the supervisor/RAG work, in plain
English, so you (or a teammate) can see what happened and why without
re-reading every diff.

**How to use this file:** newest entry at the top. One entry per logical
change (not per commit). Each entry: a one-line summary, what actually
changed, and *why* — the why is the part worth writing down, since the
diff already shows the what. Mark whether it's still uncommitted.

---

## 2026-10-25 — Updated P2 guide and shared usage/cost tracking

**Status:** included in this commit

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
existing v2 routing CSV is included with the other working-tree changes.

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
