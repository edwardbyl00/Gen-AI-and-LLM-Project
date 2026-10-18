# Routing spec

## 1. Fields and allowed values

Every incoming question is classified into a fixed record before it reaches
retrieval. These are the fields the router must produce:

| Field          | Type   | Allowed values                       | Required when |
| -------------- | ------ | ------------------------------------ | ------------- |
| `route`        | enum   | `price` / `policy` / `both` / `none` | always        |
| `false_belief` | bool   | `true` / `false`                     | always        |
| `answerable`   | bool   | `true` / `false`                     | always        |
| `reason`       | string | one sentence explaining the decision | always        |

`reason` is required for every question, including the straightforward ones.
A wrong label that looks routine is the hardest kind to debug, and the reason
is what gets written to the step log. Where a rule from section 3 applies,
the reason cites it (e.g. "R3"); the rule numbers double as codes for
grouping failures in evaluation, so no separate code field is needed.

The user's question is the router's input and already sits in the shared
state, so it is not repeated in this output.

## 2. Definitions

### route: price / policy / both / none

- **`price`**: the answer comes from past HDB resale transactions, meaning
  what flats actually sold for, filtered by town, flat type and period
  (e.g. "What was the median price of a 4-room resale flat in Tampines in
  2024?", "How many 5-room flats in Bishan were sold last year?"). The price
  agent (P1) holds only the resale transactions table from data.gov.sg
  (January 2017 onwards). Figures written in a rule, such as grant amounts,
  levies, income ceilings or CPF limits, are **not** `price`; they come from
  the policy pages. Exact filters, date range and outputs to be confirmed
  with P1.
- **`policy`**: the question asks about a rule, eligibility condition,
  procedure or timeline, including any amount that is stated in a rule
  (e.g. "What is the Minimum Occupation Period?", "Can I use CPF OA savings
  to buy a home?", "How much is the Enhanced CPF Housing Grant?").
- **`both`**: answering needs a rule from the policy pages *and* a figure
  from resale transactions together (e.g. "Can I use my CPF to buy a 4-room
  resale flat in Tampines, and what do they usually cost?"): the CPF rule
  answers the first part, the resale prices answer the second.
- **`none`**: no source holds anything relevant, so no agent is called
  (e.g. "What's the weather today?"). `none` decides what to look up, not
  whether the question can be answered; that is `answerable`'s job.

### false_belief: true / false

`true` when the question's premise assumes something that is factually
incorrect given the current policy corpus, and answering it straight would
affirm that false premise. Example: "Since MOP was abolished last year, can I
sell my flat immediately?" — MOP has not been abolished, so the premise is
false. The router flags this so the downstream agent corrects the premise
instead of answering as if it were true.

`false` for questions with no embedded false premise, including questions
that are simply unanswerable for other reasons (see `answerable`).

A flagged belief always gets a lookup: correcting it needs evidence, so
`false_belief = true` never goes with `route = none` (see R3 and section 4).

### answerable: true / false

`true` if the question can, in principle, be answered from the available
policy/price corpus (regardless of whether it needs further retrieval).

`false` if it cannot be answered even with perfect retrieval — e.g. it asks
about a jurisdiction, time period, or program not covered by the corpus, or
it asks for something no document could ever contain (pure opinion,
future-prediction with no basis).

`answerable` is independent of `route`. A question can be unanswerable yet
still worth a lookup: "Will 4-room prices in Tampines drop next year?" is
`route = price`, `answerable = false`. The system declines to predict, but
shows recent Tampines prices as context.

Why: separating "what to look up" from "can we answer it" lets the assistant
still give useful facts around a question it cannot fully answer, which
matches the rule of answering the factual part and declining the judgement.

## 3. Tie-break rules

### Rules summary

- **R1. Personal finances.** If answering would need the user's own
  financial situation (income, savings, loans), `answerable = false`. We
  never ask for or use personal financial data. If the user volunteers
  figures anyway, the system does not use them and does not repeat them
  back. Route to the general facts instead: the rules that decide
  affordability (policy) and typical prices (price), offered as context.
- **R2. Vague time words.** Words like "recently" or "lately" do not make a
  question unanswerable. The supervisor routes normally; the price agent
  turns the words into an exact period, and the answer states the period
  used.
- **R3. A flagged belief adds its source.** When `false_belief = true`, the
  route must include the source that can correct the belief, even if the
  user only asked for something else.
- **R4. The future.** A question about the future is answerable only if an
  official source has already announced the change with an effective date.
  Otherwise `answerable = false`, and current facts may be offered as
  context.
- **R5. On topic but outside our data.** If the question is in our domain
  but our sources do not hold the answer, `answerable = false`. Context is
  offered only if it is the same kind of thing the user asked about;
  similar but different data is not substituted.

### Rulings

**G1.** "Is a 4-room flat in Punggol affordable on my salary?"
- Ruling: `route = both`, `false_belief = false`, `answerable = false`
- Rule: R1
- Reason: affordability depends on the user's income, savings and loans,
  which we do not hold and must not ask for. What we can give is both
  halves of the general picture: the rules that decide affordability (e.g.
  the cap on loan repayments as a share of income, quoted from the policy
  pages) and typical 4-room prices in Punggol. The user connects the two.
- Contrast: "Is $600k a good price for a 4-room in Bedok?" is answerable,
  because it compares a price with the market, not with the user's means.

**G2.** "What did 5-room flats in Bishan go for recently?"
- Ruling: `route = price`, `false_belief = false`, `answerable = true`
- Rule: R2
- Reason: one job, one owner. Turning vague wording into exact filters is
  the price agent's job (P1). If the supervisor also did it, the two could
  disagree and a wrong price could not be traced to either.

**G3.** "Since singles can't buy resale flats at all, what's the cheapest
2-room in Yishun?"
- Ruling: `route = both`, `false_belief = true`, `answerable = true`
- Rule: R3
- Reason: the belief is false (singles can buy resale flats under HDB's
  eligibility rules; the policy agent must confirm the exact conditions from
  the pages). Correcting it needs the policy pages, and the price part needs
  the resale table, so both are called.

**G4.** "Will the CPF housing rules change next year?"
- Ruling: `route = policy`, `false_belief = false`, `answerable = false`
  (unless the corpus contains an announced change with a future effective
  date, in which case `answerable = true`)
- Rule: R4
- Reason: unlike prices, rule changes are sometimes announced in advance,
  and our passages carry effective dates. An announced change is a fact; an
  unannounced one is speculation. Current rules are offered as context.

**G5.** "How much is a BTO flat in Tengah?"
- Ruling: `route = none`, `false_belief = false`, `answerable = false`
- Rule: R5
- Reason: our price data covers resale transactions only. Resale prices are
  not substituted, because a resale flat and a new BTO flat are different
  products and the comparison could mislead.

## 4. Invalid combinations and what to do

Guiding rule: when the router's output cannot be trusted, choose the
fallback whose mistake does the least harm. Every fallback is recorded in the
step log with the code `invalid_combo` or `malformed_output`, so it shows up
in evaluation instead of being hidden.

| Combination | Why it is invalid | What the system does |
| ----------- | ----------------- | -------------------- |
| `route = none` with `answerable = true` | Nothing is looked up, so there is no source to answer from | Set `answerable = false` and reply that the system cannot help with this question |
| `route = none` with `false_belief = true` | A false belief can only be corrected with evidence; with no lookup the system would be correcting from the model's own memory, which is what the plain chatbot (V0) does | Set `route = policy` so the policy agent looks for the correcting rule; if it finds nothing, the normal "I don't know" path applies |
| Missing field, a value outside the allowed list, a reply that is not valid JSON, or an API failure after the library's own retries | The output cannot be read reliably | Retry routing once; if it fails again, use `route = none`, `false_belief = false`, `answerable = false` |

## 5. Worked examples

Clean, typical cases, one per question kind, plus one for `route = none`.
These become the few-shot examples in the supervisor prompt, so **none of
these questions may appear in the practice or held-out sets** (that would
let the router see the answers to its own test).

**E1. Rules only**
Question: "What is the Minimum Occupation Period for a resale flat?"
```json
{"route": "policy", "false_belief": false, "answerable": true,
 "reason": "Asks for a rule stated on the HDB pages; no resale prices needed."}
```

**E2. Numbers only**
Question: "What was the median resale price of a 3-room flat in Ang Mo Kio in 2023?"
```json
{"route": "price", "false_belief": false, "answerable": true,
 "reason": "Asks for a statistic from past resale transactions with a clear town, flat type and year."}
```

**E3. Both together**
Question: "Can a first-time couple get a CPF housing grant for a resale flat, and what do 4-room flats in Jurong West usually sell for?"
```json
{"route": "both", "false_belief": false, "answerable": true,
 "reason": "Needs a grant rule from the policy pages and typical prices from resale transactions."}
```

**E4. Built on a myth**
Question: "Since you can't use CPF savings for resale flats, how much cash would I need for a 3-room in Woodlands?"
```json
{"route": "both", "false_belief": true, "answerable": true,
 "reason": "Assumes CPF cannot be used for resale flats, which is false; policy is needed to correct it (R3) and price to answer the cost."}
```

**E5. Cannot be answered**
Question: "Will 5-room prices in Sengkang go up in 2027?"
```json
{"route": "price", "false_belief": false, "answerable": false,
 "reason": "Asks for a forecast, which no source can give (R4); recent Sengkang 5-room prices are like-for-like context."}
```

**E6. Out of scope**
Question: "What's a good interest rate for a car loan?"
```json
{"route": "none", "false_belief": false, "answerable": false,
 "reason": "Not about HDB, CPF housing rules or resale prices; no source holds anything relevant."}
```

## 6. Dependencies and proposals

### Answers needed from teammates

- **P1:** what does the price agent take "recently" to mean by default
  (e.g. the latest 12 months of data)? Needed for R2.
- **P4/P5:** does the corpus contain any announced CPF or HDB changes with a
  future effective date? Needed to label G4 style questions correctly.

### Proposal for phase 2 (needs team agreement)

**Income scenario table.** For affordability questions, the answer shows a
fixed set of illustrative household incomes and the repayment cap at each.
Design rules:
1. The system picks the bands, never the user; the same bands for everyone,
   with edges set at HDB's own income thresholds so the cliffs are visible.
2. Show only what the rules directly determine (the repayment cap), never
   "you can afford a flat up to $Y".
3. The cap is quoted from the policy pages with link and date; the
   multiplication is done in code, not by the LLM; the table is labelled
   "illustrative, not an assessment of your situation"; the answer never
   points the user to a row.

## 7. Requirements this spec places on synthesis

The router's decisions only work if the answer respects them. These go into
the merged synthesis prompt (P2):

- `false_belief = true`: correct the belief first, with a cited source,
  before answering the rest (R3).
- `false_belief = true` is the router's suspicion, based on the model's own
  knowledge (the router cannot see the sources). Synthesis corrects the
  belief only when the retrieved evidence contradicts it; if the evidence
  supports it, the belief is treated as true.
- `answerable = false` with a lookup: present the facts as context only;
  never turn them into a prediction or a recommendation (R4, R5).
- Personal figures volunteered by the user are never used or repeated
  back (R1).
- When vague time words were used, state the exact period the prices cover
  (R2).

## 8. Future work (for the report)

- A personal affordability calculator built as a deterministic tool, with
  explicit consent, no data stored and a clear "not financial advice"
  boundary.
