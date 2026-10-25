# Price agent (P1)

Answers the price part of a question with exact figures from HDB resale
transactions (data.gov.sg, January 2017 onwards).

## Use

```python
from agents.price import price_agent
price_agent("What did 4-room flats in Tampines sell for recently?", "2026-10-25")
```

Returns the fields agreed in `Docs/p2_supervisor_contract.md` (A4):
`town`, `flat_type`, `period_start`, `period_end`, `median_price`,
`min_price`, `max_price`, `n_deals`, `data_as_of`, plus:

| Extra field | Meaning |
|---|---|
| `mean_price` | The average price, for questions that ask for an average rather than a typical price |
| `approach` | Which price agent approach produced the result (`A_filter_tool`) |
| `filters` | What the LLM extracted from the question, for the step log |
| `note` | Anything synthesis should tell the user (period used, no data), or `null` |

`town` or `flat_type` is `"ALL"` when the question names none.

## Rules

- **"Recently", "lately" or no time words** mean the latest 12 full months
  of data (`price_agent.default_months` in `config.yaml`). The newest month
  is skipped because it is still filling up.
- **"Last N months"** means the latest N full months of data.
- **Periods outside the data** (for example next year) return 0 deals and a
  note. Prices are never guessed or predicted.
- **The LLM only extracts filters.** All numbers are calculated by code.

## Files

| File | Purpose |
|---|---|
| `agent.py` | `price_agent()`: the entry point |
| `extract.py` | Approach A: LLM fills in town, flat type and period |
| `data.py` | Loads the table, period rules, price calculations (no LLM) |
| `prompts/price_filters_v1.md` | Prompt for the filter extraction |

## Rebuild the price data

1. Download the CSV from data.gov.sg into `data/raw/` (file name in `config.yaml`).
2. Run `python -m scripts.clean_prices` from the project root.

## Tests

`pytest tests/test_price_agent.py` (no API key needed).
