# Demo interface (P1)

```
streamlit run ui/app.py
```

Live modes read `OPENAI_API_KEY` (or `LLM_API_KEY`) from the project root's
local `.env` file or the server environment. The page starts in Full System
when a key is present, otherwise in Demo Mode. The sidebar shows whether a
key was detected; this does not validate the key with the provider. Keep
`.env` out of Git.

Shows the answer, its sources with dates, the price facts used and each agent
step. The sidebar switches between:

- **Full system**: the supervisor pipeline, with price agent approach A or B
- **Plain chatbot (baseline)**: the same LLM with no agents or sources
- **Demo mode (saved samples)**: three saved answers built from the real price
  data, no API calls. Use it to preview the page without a key, or as a backup
  if the API is down during the presentation.

`sample_answers.json` holds the demo-mode answers. Price figures are real;
the answer text was written to show the layout.
