# P1 review of synthesis rules (synthesis_v1.md, routing branch)

Reviewer: P1 (price agent). Focus: how synthesis uses price facts.

## Must fix

1. **`mean_price` and `note` are dropped before the model sees them.**
   `synthesis.py` copies only these price fields into the prompt: town,
   flat_type, period_start, period_end, median_price, min_price, max_price,
   n_deals, data_as_of. The price agent also returns:
   - `mean_price`: needed for "average" questions. Without it, held-out
     question H29 ("average resale price ... last six complete months")
     cannot be answered, and A5 forbids calculating it.
   - `note`: tells the user which period was used for vague words
     ("No exact period asked; used the latest 12 full months.") or why
     there is no data ("the data only goes up to 2026-10").
   Suggested fix: add `"mean_price"` and `"note"` to the key list in
   `synthesis.py`, and in A5 say "use mean_price only when the user asks
   for an average; otherwise use median_price".

2. **"ALL" needs explaining.** When a question names no town or flat type,
   the price agent returns `"ALL"`. Suggest adding to A5: "If town or
   flat_type is ALL, say the figure covers all towns (or all flat types)."

## Suggested additions to A5 (prices)

3. **Past deals, not today's prices.** Add: "Say that these are past resale
   transaction prices, not current asking prices."
4. **Zero deals.** A5 covers fewer than 10 deals; add: "If n_deals is 0,
   say no resale deals matched and give the note's reason."
5. **Min and max are single deals.** Add: "min_price and max_price are the
   lowest and highest single deals, not a typical range."
6. **Comparing a user's figure.** For "Is $550k too much for a 3-room in
   Bedok?" (routing spec G1 contrast, answerable), synthesis may say where
   $550k sits against the median and the lowest and highest deals, but must
   not call it good or bad value (A6).

## A7 (dates): conflict with the corpus

7. P5 found that 0% of the 1,282 policy chunks have an `effective_date`
   (Docs/p5_status.md on the `kay` branch). So A7 will almost never fire,
   and answers will have no dated sources, which the proposal promised.
   Suggest: when `effective_date` is missing, show the capture date as
   "retrieved on [date]" in the source list (built by code), and never call
   it an effective date. P4 and P5 should confirm which field holds the
   capture date (`retrieved_at` or `collection_date`).

## Fine as they are

- A1, A2, A3, A4, A6, A8: no concerns from the price side.
- A5 "never calculate new figures": agreed. The price agent already gives
  median, mean, min, max and the deal count, so synthesis never needs to.
