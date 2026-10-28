# Demo interface (P1)

```
streamlit run ui/app.py
```

Shows the answer, its sources with dates, the price facts used and each agent
step. The sidebar switches between:

- **Full system**: the supervisor pipeline, with price agent approach A or B
- **Plain chatbot (baseline)**: the same LLM with no agents or sources
- **Demo mode (saved samples)**: three saved answers built from the real price
  data, no API calls. Use it to preview the page without a key, or as a backup
  if the API is down during the presentation.

`sample_answers.json` holds the demo-mode answers. Price figures are real;
the answer text was written to show the layout.
