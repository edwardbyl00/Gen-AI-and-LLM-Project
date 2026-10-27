# Routing evaluation summary — `routing_supervisor_v1_20261025_1424.csv`

Source run: `evaluation/results/routing_supervisor_v1_20261025_1424.csv`
Prompt: `supervisor_v1.md` | Questions: `data/labels/practice_routing.csv` (54 rows, up from 20 in the previous run)

## Overall accuracy

| Field | Correct | Rate |
|---|---|---|
| `route` | 49/54 | 91% |
| `false_belief` | 45/54 | 83% |
| `answerable` | 47/54 | 87% |
| **All three correct** | 35/54 | **65%** |
| Myths detected | 5/14 | 36% |
| False alarms | 0/40 | 0% |
| Safety-check events | 0 | — |

## Route confusion (rows = label, columns = router)

```
          price  policy    both    none
 price       6       0       0       0
policy       0      35       1       0
  both       0       1       5       2
  none       0       0       0       3
```

`route` itself is solid (91%) — the two `both→none` misses below explain most of the slip.

## Headline finding: myth detection is weak, with a clear pattern

Only 5/14 myth questions were flagged (`false_belief` recall = 36%). Almost
every miss follows the same shape: **the router declines
(`answerable: False`) the moment a personal number or detail appears in
the question**, even when the actual question is a general policy rule,
not something that genuinely depends on the user's finances.

Examples:
- *"What are the type of grants for a person earning 80k a year?"* →
  labelled answerable (it's asking what grants exist — a general
  eligibility rule), router declined because "80k" appears.
- *"My brother transferred his HDB flat to me... Can I take an HDB loan?
  Can I use the HFE grant?"* → labelled false_belief (there's a real
  misconception about transfers/loans), router didn't flag it, called it
  a plain policy question.
- *"What is the income Ceiling for a single to buy a HDB flat"*,
  *"How much CPF SA money can I use?"*, *"What happens to my CPF when I
  sell the flat?"*, *"How long do PR holders need to wait before buying
  resale?"* — all labelled as myths, router missed every one. These read
  like genuine eligibility/rule questions with an implicit wrong
  assumption baked in (e.g. assuming no waiting period, assuming
  unlimited CPF use) that R3 should have caught but didn't.

This is a routing-prompt issue (R1's "personal finances → not answerable"
rule, and the false-belief examples in `supervisor_v1.md`) — separate
from the retrieval-layer issue found earlier with the "18-year-old BTO"
question, where routing correctly flagged `false_belief: true` and the
failure was downstream, at evidence assessment.

## The two `both → none` misses

*"Does a major transformation project bump up resale prices nearby?"*
and *"What is the best strategy to maximise returns from an HDB flat?"*
— both correctly recognized as outside what the data can answer (no
causal/investment-strategy data), but labelled `both` rather than `none`.
Worth double-checking whether these labels are right, or whether the
router's `none` is actually the better call here — this might be a label
issue, not a router issue.

## Data-hygiene note

This saved run has two different questions both under
`question_id PR_P2_29`. The current `data/labels/practice_routing.csv`
no longer has that duplicate (54 unique IDs) — already fixed — just
flagging it since this particular saved CSV still has it.

## Answer-scoring status

`evaluation/answers/answers_20261025_1442.csv` (54 rows, generated
2026-10-25 14:42) is **still ungraded** — `grade_myth_accepted` is blank
on all 14 myth rows. Running `score_answers.py score` on it as-is will
stop with `Ungraded row`. Grade it (see `Docs/p2_supervisor_code.md`
section 4, "Check final answers") before scoring.

## Full list of misses (19 of 54)

| Question ID | Question | What differed | Router's reason |
|---|---|---|---|
| PR_P2_13 | My single sister will have to buy a BTO, so what do resale 2-room flats in Jurong East cost for comparison? | `answerable: True → False` | Assumes a single sister must buy a BTO, which may be false and needs policy to correct (R3), but the BTO comparison part isn't covered by the sources. |
| PR_P2_22 | What are the type of grants for a person earning 80k a year? | `answerable: True → False` | Grant eligibility/amounts are policy matters, but answering for someone earning $80k depends on personal financial circumstances. |
| PR_P2_23 | I am 18 and finally able to bto without being married. What is needed on my end to apply for a bto? | `answerable: True → False` | Assumes an untrue rule that an 18-year-old can apply for a BTO unmarried; policy is needed to correct it (R3), and full application details aren't fully covered (R5). |
| PR_P2_25 | What is the income Ceiling for a single to buy a HDB flat | `false_belief: True → False` | Asks for an eligibility rule/amount set by HDB policy, not resale transaction data. |
| PR_P2_26 | How much CPF Special Account (SA) money can I use? | `false_belief: True → False` | Asks about CPF housing usage rules — how much SA savings can be used — governed by official CPF/HDB policy. |
| PR_P2_28 | What would be the monthly payment I need to pay every month if I purchase the BTO flat in Tengah | `route: both → both` (case only); `false_belief: True → False` | Monthly payment depends on the buyer's own loan amount, tenure, rates and finances (R1). |
| PR_P2_29 | What happens to my CPF when I sell the flat? | `false_belief: True → False` | Asks about CPF housing rules on sale proceeds/refund, covered by official CPF/HDB policy pages. |
| PR_P2_29 | What is the maximum loan I can get? | `answerable: True → False` | Maximum loan depends on the user's own income/finances; only general loan rules can be given. |
| PR_P2_30 | I am planning for my first HDB purchase... searching for a unit within 1km of Opera Estate Primary School. | `route: both → policy`; `answerable: True → False` | Eligibility checks/grants are policy matters, but finding a unit near a specific school isn't covered. |
| PR_P2_31 | My brother transferred his HDB flat to me without selling it, but I need to pay for his CPF refund. Can I take an HDB loan? Can I still use the HDB grant given in HFE? | `false_belief: True → False` | Asks about transfer, CPF refund, loan eligibility and HFE grant use — all policy rules/procedures. |
| PR_P2_32 | What happens to an HDB after the 99-year lease expires? | `false_belief: True → False` | Asks about the legal/policy outcome when a lease ends, governed by HDB/statute rules. |
| PR_P2_34 | Does a major transformation project bump up the resale price of flats nearby? | `route: both → none` | Asks for a causal effect, but sources only provide transaction records without project linkage. |
| PR_P2_35 | What is the best strategy to maximise returns from an HDB flat? | `route: both → none` | Asks for investment strategy/optimisation advice, not HDB/CPF rules or resale statistics. |
| PR_P2_36 | If I am over 70 years old and just sold my private property, can I appeal to HDB to waive the 30-month waiting period before buying a 5-room unit directly from them? | `answerable: False → True` | Asks about an HDB eligibility rule and whether an appeal/waiver exists — governed by official policy. |
| PR_P2_37 | Is there any way to buy before the 15-month wait-out period? | `false_belief: True → False` | Asks about an eligibility restriction and whether exceptions exist, governed by HDB policy. |
| PR_P2_38 | How long do PR holders need to wait before they can buy a resale HDB? | `false_belief: True → False` | Asks for an eligibility waiting-period rule for PR buyers, stated in official HDB policy pages. |
| PR_P2_42 | How do I work out a budget to finance the flat purchase? | `route: policy → both` | Working out a personal budget isn't answerable (R1); policy gives the general rules. |
| PR_P2_44 | The HFE letter application e-Service is unavailable. How can I apply for HFE and participate in this sales exercise? | `false_belief: True → False` | Asks about the official procedure/workaround for applying for HFE and joining a sales exercise. |
| PR_P2_45 | How do I apply for a flat in this sales exercise? | `answerable: True → False` | Asks about application steps, but the available policy source covers general rules, not this specific procedure. |
