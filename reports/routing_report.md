# Routing Report — Supervisor Router

This covers the routing portion of AskGov SG: [agents/supervisor/router.py](../agents/supervisor/router.py), classifying each user question before retrieval or answering happens.

## What the router does

Given a question, the router makes one LLM call (structured JSON output, schema-enforced) and returns:

- **route** — which source(s) to search: `price` (HDB resale transactions), `policy` (HDB/CPF/statute rules), `both`, or `none`.
- **check_premise** — whether the question assumes a specific claim about rules, amounts, timelines or prices that should be checked against the sources before answering (previously called `false_belief`; renamed because the router flags premises to verify, not confirmed falsehoods — the answer step decides if the claim is true or false).
- **answerable** — whether the actual question can be answered from the two sources at all, independent of which source(s) are relevant.
- **reason** — one sentence citing the deciding rule.

Five rules (R1–R5) in the prompt (`agents/supervisor/prompts/supervisor_v2.md`) cover the recurring edge cases: personal-finance questions are unanswerable even with real numbers given (R1), vague time words don't block routing (R2), a flagged premise must route to a source that can check it (R3), forward-looking questions need an announced change to be answerable (R4), and questions in-domain but outside what the sources hold are unanswerable (R5).

## Evaluation setup

- Labels: [data/labels/practice_routing.csv](../data/labels/practice_routing.csv) — 54 hand-labelled questions (route, check_premise, answerable), covering price lookups, policy lookups, mixed questions, out-of-scope questions, and questions with a false or misleading premise baked in.
- Runs compared:
  - **v1** — `evaluation/results/routing_supervisor_v1_20261025_1424.csv`, prompt `supervisor_v1.md`.
  - **v2** — `evaluation/results/routing_supervisor_v2_20261025_1930.csv` (latest), prompt `supervisor_v2.md`.

## Results: v1 → v2

| Field | v1 | v2 (latest) |
|---|---|---|
| `route` correct | 49/54 (91%) | 49/54 (91%) |
| `check_premise` correct | 45/54 (83%) | 51/54 (94%) |
| `answerable` correct | 47/54 (87%) | 47/54 (87%) |
| **All three correct** | 35/54 (65%) | 40/54 (74%) |
| Premise-flagging recall (myths caught) | 5/14 (36%) | 9/12 (75%) |
| False alarms (flagged but no premise) | 0/40 | 0/42 |

v2 roughly doubled premise-flagging recall and lifted the three-way accuracy from 65% to 74%, with zero false alarms in both versions — the router never over-flags a clean question.

## What changed between v1 and v2, and why it mattered

v1's biggest failure mode: the moment a question contained a personal detail (an age, an income figure, a specific flat), the router declined it under R1 even when the actual question was a general eligibility rule the policy sources do cover (e.g. *"What are the type of grants for a person earning 80k a year?"*, *"How much CPF SA money can I use?"*). This conflated "a number appears in the question" with "the question needs the user's personal finances," and it also meant real premise-questions like PR holder waiting periods or lease expiry were being waved through as plain policy questions instead of flagged.

v2 tightened the distinction between route and answerable, and reworded `check_premise` to center on "a specific claim that should be checked" rather than "a false belief," which seems to have helped the model stop pattern-matching on personal numbers and start reading what the question was actually assuming. That's the main driver of the recall jump from 36% to 75%.

## Remaining failure patterns (v2)

Full miss list: `evaluation/results/routing_supervisor_v2_20261025_1930.csv`, 14 of 54 rows. Three recurring shapes:

1. **Procedure/process questions read as unanswerable.** *"How do I opt for Deferred Income Assessment in the application form?"*, *"When will I be notified of the ballot results?"* — the router sometimes treats a specific-sounding procedural question as too narrow for the sources, when the policy pages do cover it. (Also the reverse: *"How do I apply for a flat in this sales exercise?"* flagged unanswerable when labelled answerable.)
2. **R1 (personal-finance) still over-applies to routing, not just answerability.** *"What would be the monthly payment... if I purchase the BTO flat"*, *"How do I work out a budget to finance the flat purchase?"* — correctly marked unanswerable, but the router also drops `price` from the route when the label expects `both` (general price context should still be looked up even though the personalized number can't be computed).
3. **A few premises still slip through.** *"How much CPF Ordinary Account (OA) money can I use?"* and *"How long do PR holders need to wait before they can buy a resale HDB?"* are both phrased as if the asker is only asking "what's the rule," but the label treats the implicit assumption (that the asker is eligible to use OA, that a universal wait period exists) as a premise to check — a genuinely fine line, and possibly worth revisiting whether these labels are drawing it correctly rather than treating this purely as a router miss.

## Takeaways

- The rename from `false_belief` → `check_premise` and the clarified R1/R3 wording in v2 produced a real accuracy gain, not just a cosmetic one — worth keeping as the baseline going forward.
- Next highest-leverage fix is likely R1: separate "can't compute a personalized number" (answerable: false) from "drop the source from route" — v2 conflates these in a few `both→policy` misses.
- A couple of the remaining "misses" (OA/CPF rule, PR waiting period) look more like a labelling judgment call than a router defect and are worth a second pass on the label set before chasing further prompt changes.
