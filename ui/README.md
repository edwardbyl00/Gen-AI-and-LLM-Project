# HomeWise Pages

Two Streamlit pages share the HomeWise look (cream, brown and orange; Fraunces
headings and DM Sans text, loaded from Google Fonts). Run them from the project
root, one at a time.

| Page | Command |
| --- | --- |
| Main page | `streamlit run ui/app.py` |
| Chat page | `streamlit run ui/chat_app.py` |

Live answers read `OPENAI_API_KEY` (or `LLM_API_KEY`) from `.env` in the project
root. Keep `.env` out of Git.

## Main Page (`app.py`)

- **Mode switch** (top right): **Live** runs the full system, **Plain Chatbot**
  runs the same model with no agents or sources, and **Demo** shows saved answers
  with no API calls. The page starts on Live when a key is found, otherwise on Demo.
- **Answer card:** a one-line headline, then *Read the full answer* for the full
  text and its sources. For price questions the headline is built from the price
  figures; for rules questions it is the answer's opening line; for questions about
  both, it combines the two. Key numbers are shown in bold.
- **Price facts card:** median in large type, plus average, lowest and highest
  deal, the period and the number of deals. It is hidden when there are no deals,
  so no figure is ever shown without data.
- **How This Answer Was Made:** each step as a stop on a road ending at the answer,
  with its time. A failed step turns red.
- **Behind the Scenes:** the full step log, the route and why it was chosen, what
  the price agent understood, and any agent errors.
- **Sidebar** (the » at the top left): price agent approach A or B.

`sample_answers.json` holds the Demo answers. Their price figures come from the
real data; the answer text was written to show the layout.

## Chat Page (`chat_app.py`)

The chat version of the main page: follow-up questions are rewritten using the
conversation, every chat is saved on this computer, and each answer keeps its own
sources, steps, self-check verdict and cost. It needs an API key and has no Demo
mode. Answers use the same headline and *Read the full answer* style as the main
page.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Main page |
| `chat_app.py` | Chat page |
| `homewise_logo.svg` | Logo shown in both headers |
| `sample_answers.json` | Saved answers for Demo mode |
| `../.streamlit/config.toml` | Theme colours shared by both pages |

## Tests

`python -m pytest tests/test_ui_app.py` runs the main page headless in Demo mode,
with no API key.
