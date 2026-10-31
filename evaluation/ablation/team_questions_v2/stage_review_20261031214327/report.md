# Question evaluation report

Scores are rubric scores on a 0–100% scale. Pending means not reviewed; Unknown means not established; N/A means not applicable. Reference recall measures matching labeled chunks, not answer correctness.

| Query date | Executions | Unique questions | Graded executions |
| --- | --- | --- | --- |
| 2026-10-31 | 2 | 1 | 0 |

## Results by variant and category

Counts in each score show scored executions / total executions. Category rows are subsets of All; do not add them together.

| Variant | Category | Runs | Questions | Routing accuracy | Faithfulness | Correctness |
| --- | --- | --- | --- | --- | --- | --- |
| A\_baseline | All | 1 | 1 | No scores (0/1 scored) | No scores (0/1 scored) | No scores (0/1 scored) |
| A\_baseline | Category: mixed | 1 | 1 | No scores (0/1 scored) | No scores (0/1 scored) | No scores (0/1 scored) |
| B\_decomposition | All | 1 | 1 | No scores (0/1 scored) | No scores (0/1 scored) | No scores (0/1 scored) |
| B\_decomposition | Category: mixed | 1 | 1 | No scores (0/1 scored) | No scores (0/1 scored) | No scores (0/1 scored) |

## Stage results by execution

| Run | Routing | Policy coverage | Reference chunks in corpus | Candidate recall | Supplied recall | Policy decision / reason |
| --- | --- | --- | --- | --- | --- | --- |
| 1 / B\_decomposition / repeat 1 | Unknown: both (expected: unverified) | UNKNOWN | Unknown | Unknown | Unknown | Not run / not recorded |
| 1 / A\_baseline / repeat 1 | Unknown: both (expected: unverified) | UNKNOWN | Unknown | Unknown | Unknown | Not run / not recorded |

## Answer quality by execution

LLM-judge score is a pre-pass for reviewer context, not a substitute for the independent grades to its right.

| Run | LLM-judge score | Evidence relevance | Faithfulness | Correctness | Completeness | Appropriate abstention |
| --- | --- | --- | --- | --- | --- | --- |
| 1 / B\_decomposition / repeat 1 | Not judged | Pending | Pending | Pending | Pending | Pending |
| 1 / A\_baseline / repeat 1 | Not judged | Pending | Pending | Pending | Pending | Pending |

## Diagnostic observations

Flags are investigation leads, not confirmed causes. A verified corpus gap can lead to an appropriate abstention.

| Observation | Executions flagged | Total executions |
| --- | --- | --- |
| execution error | 2 | 2 |

## What went well and what needs fixing

| Run | Observations / errors | What went well | What went wrong | Recommended fix | Reviewer notes |
| --- | --- | --- | --- | --- | --- |
| 1 / B\_decomposition / repeat 1 | execution error<br>ValueError: Chroma collection does not exist: hdb\_housing\_advisory\_bge\_base\_v1\_5 | Pending review | Pending review | Pending review | Pending review |
| 1 / A\_baseline / repeat 1 | execution error<br>ValueError: Chroma collection does not exist: hdb\_housing\_advisory\_bge\_base\_v1\_5 | Pending review | Pending review | Pending review | Pending review |

## Questions and answers

| Run | Question | Answer |
| --- | --- | --- |
| 1 / B\_decomposition / repeat 1 | Since singles can't buy resale flats, what's the cheapest 2-room in Yishun? | I couldn’t confirm the claim that singles cannot buy resale flats from the official policy sources I have, because no policy passage was provided.<br><br>For prices, the cheapest recorded HDB resale transaction for a 2-room flat in Yishun was $190,000 during 2017-01 to 2026-10, based on 392 transactions. This is from historical resale transaction data, not a current listing or valuation.<br><br>I couldn’t find the singles eligibility rules in the official sources I have, so please check the linked official HDB/CPF page for the latest position.<br><br>Can't answer:<br>- Whether singles can buy HDB resale flats: no policy passage was provided to confirm or correct the claim<br>- Relevant eligibility conditions for singles buying resale flats: no policy passage was provided<br>- Any flat-type conditions relevant to singles purchasing resale flats: no policy passage was provided |
| 1 / A\_baseline / repeat 1 | Since singles can't buy resale flats, what's the cheapest 2-room in Yishun? | I couldn’t confirm the claim that singles cannot buy resale flats from the official policy sources I have, because no policy passage was provided.<br><br>For Yishun 2-room resale transactions, the cheapest recorded price in the latest 12 full months was $318,000, for 2-room flats in Yishun during 2025-10 to 2026-09, based on 54 transactions. The median was $362,500 over the same period, based on 54 transactions.<br><br>If you want, I can also give the mean and highest recorded prices for the same Yishun 2-room period.<br><br>Can't answer:<br>- Whether singles can buy resale flats: no policy passage was provided, so I could not confirm the eligibility rule from the official sources I have |
