"""AskGov SG demo interface (P1).

Shows, for one question: the answer, the price facts used (as a price strip
from the lowest to the highest deal), the sources, and each agent step.
A sidebar switches between the full system, the plain chatbot baseline and
demo mode, and between price agent approaches A and B.

Run from the project root:
    streamlit run ui/app.py

"Demo mode" shows saved sample answers (real price figures, no API calls), so
the page can be previewed without an API key, or used as a backup if the
API is down during the presentation.
"""

import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")
HAS_LLM_KEY = bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"))

SAMPLES_FILE = Path(__file__).parent / "sample_answers.json"
DEMO, FULL, CHATBOT = "Demo Mode (Saved Samples)", "Full System", "Plain Chatbot (Baseline)"
EXAMPLES = [
    "What did 4-room flats in Tampines sell for recently?",
    "Will 4-room flats in Tampines cost more next year?",
    "How much is a 5-room resale flat in Tengah?",
    "Can I use my CPF for a 3-room resale flat in Clementi, and roughly how much would it cost?",
]
STEP_NAMES = {
    "router": "Worked out what the question needs",
    "price_agent": "Looked up past resale deals",
    "policy_agent": "Searched the HDB and CPF pages",
    "synthesis": "Wrote the answer from what was found",
    "chatbot": "Answered from the model's own memory (no sources)",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap');
html, body, [class*="st-"], .stMarkdown, button, input, textarea {
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif;
}
.block-container { max-width: 780px; padding-top: 2.5rem; }

.ag-header { margin-bottom: 1.25rem; }
.ag-header h1 { font-size: 2.6rem; line-height: 1.1; margin: 0 0 .4rem; color: #102A43;
  letter-spacing: -0.01em; }
.ag-header p { font-size: 1.1rem; color: #486581; margin: 0; max-width: 34em; }

div.stButton > button { border-radius: 10px; border: 1px solid #D9E2EC; background: #FFFFFF;
  color: #102A43; text-align: left; justify-content: flex-start; padding: .7rem .9rem;
  min-height: 3.6rem; line-height: 1.35; }
div.stButton > button:hover { border-color: #0F7C7A; color: #0F7C7A; }
div.stButton > button:focus-visible { outline: 3px solid #E8A33D; outline-offset: 2px; }

.ag-status { font-size: .95rem; color: #486581; margin: .25rem 0 .5rem; }
.ag-status b { color: #0F7C7A; }
.ag-status.ag-declined b { color: #9F580A; }

.ag-strip { background: #FFFFFF; border: 1px solid #D9E2EC; border-radius: 12px;
  padding: 1.1rem 1.25rem 1.4rem; margin: 1rem 0; }
.ag-strip h3 { font-size: 1.05rem; margin: 0 0 .2rem; color: #102A43; }
.ag-strip .ag-scope { color: #486581; font-size: .95rem; margin-bottom: .3rem; }
.ag-track { position: relative; height: 10px; border-radius: 5px; background: #D9E2EC;
  margin: 2.6rem .5rem 0; }
.ag-mark { position: absolute; top: -6px; width: 4px; height: 22px; border-radius: 2px;
  transform: translateX(-50%); }
.ag-mark.ag-median { background: #E8A33D; }
.ag-mark.ag-mean { background: #0F7C7A; }
.ag-mark span { position: absolute; bottom: 28px; left: 50%; transform: translateX(-50%);
  white-space: nowrap; font-size: .9rem; color: #102A43; }
.ag-mark.ag-mean span { bottom: auto; top: 28px; color: #0F7C7A; }
.ag-ends { display: flex; justify-content: space-between; margin-top: 2.4rem;
  font-size: .9rem; color: #486581; }
.ag-ends b { color: #102A43; font-size: 1.05rem; }
.ag-note { font-size: .9rem; color: #486581; margin-top: .8rem; }
.ag-few { color: #9F580A; }

.ag-steps { list-style: none; padding: 0; margin: .25rem 0 0; }
.ag-steps li { position: relative; padding: 0 0 1rem 1.6rem; color: #102A43; }
.ag-steps li::before { content: ""; position: absolute; left: 4px; top: .35rem; width: 10px;
  height: 10px; border-radius: 50%; background: #0F7C7A; }
.ag-steps li::after { content: ""; position: absolute; left: 8px; top: 1.1rem; bottom: -.2rem;
  width: 2px; background: #D9E2EC; }
.ag-steps li:last-child::after { display: none; }
.ag-steps li.ag-error::before { background: #B42318; }
.ag-steps small { color: #829AB1; margin-left: .35rem; }
.ag-footer { font-size: .85rem; color: #829AB1; margin-top: 2rem; }

@media (max-width: 640px) { .ag-header h1 { font-size: 2rem; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
"""


# ---------- getting an answer ----------

def load_samples():
    with open(SAMPLES_FILE, encoding="utf-8") as f:
        return {s["question"]: s for s in json.load(f)["samples"]}


def get_answer(question, mode, approach):
    """Return a pipeline-shaped bundle for the question (None if demo mode has no sample)."""
    if mode == DEMO:
        return load_samples().get(question)
    if mode == CHATBOT:
        from agents.baselines.plain_chatbot import chatbot_answer
        return chatbot_answer(question)
    from agents.price import price_agent, price_agent_sql
    from agents.supervisor.pipeline import handle_question
    price_fn = price_agent if approach == "A" else price_agent_sql
    return handle_question(question, price_fn=price_fn)


# ---------- small formatting helpers ----------

def money(value):
    return "n/a" if value is None else f"${value:,.0f}"


def plain_text(text):
    """Escape $ so Streamlit does not read '$665,000 ... $510,000' as a maths formula."""
    return str(text).replace("$", "\\$")


def nice(name):
    """'KALLANG/WHAMPOA' -> 'Kallang/Whampoa', '4 ROOM' -> '4-room'."""
    name = str(name)
    if name.endswith(" ROOM"):
        return name.replace(" ROOM", "-room")
    return name.title()


def month_name(ym):
    """'2025-10' -> 'Oct 2025'."""
    try:
        return datetime.strptime(str(ym), "%Y-%m").strftime("%b %Y")
    except ValueError:
        return str(ym)


def position(value, low, high):
    """Where a value sits on the strip, as a percentage."""
    if value is None or high == low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))


# ---------- the sections ----------

def flat_and_town(price):
    """'4 ROOM', 'TAMPINES' -> '4-Room Flats in Tampines' (title case for headings)."""
    flat_type, town = price.get("flat_type"), price.get("town")
    flats = "All Flat Types" if flat_type == "ALL" else f"{nice(flat_type).title()} Flats"
    where = "All Towns" if town == "ALL" else nice(town)
    return f"{flats} in {where}"


def price_strip_html(price):
    """The key figures: lowest deal to highest deal, with median and average marked."""
    period = f"{month_name(price.get('period_start'))} to {month_name(price.get('period_end'))}"
    n = price.get("n_deals") or 0
    scope = f"{period}, {n:,} resale deal{'s' if n != 1 else ''}"
    parts = ['<div class="ag-strip" role="group" aria-label="Price facts">',
             f"<h3>Price Facts: {html.escape(flat_and_town(price))}</h3>",
             f'<div class="ag-scope">{scope}</div>']

    low, high = price.get("min_price"), price.get("max_price")
    if n and low is not None and high is not None:
        med, mean = price.get("median_price"), price.get("mean_price")
        parts += [
            '<div class="ag-track">',
            f'<div class="ag-mark ag-median" style="left:{position(med, low, high):.1f}%">'
            f"<span>Median {money(med)}</span></div>",
            f'<div class="ag-mark ag-mean" style="left:{position(mean, low, high):.1f}%">'
            f"<span>Average {money(mean)}</span></div>",
            "</div>",
            f'<div class="ag-ends"><div>Lowest Deal<br><b>{money(low)}</b></div>'
            f'<div style="text-align:right">Highest Deal<br><b>{money(high)}</b></div></div>',
        ]
        if n < 10:
            parts.append('<div class="ag-note ag-few">Based on fewer than 10 sales, '
                         "so treat these figures with care.</div>")
    elif price.get("note"):
        # No figures to show: the reason belongs up here, not in the details.
        parts.append(f'<div class="ag-note">{html.escape(price["note"])}</div>')
    if price.get("stub"):
        parts.append('<div class="ag-note ag-few">Stub data: not real prices.</div>')
    parts.append("</div>")
    return "".join(parts).replace("$", "&#36;")


def show_main(bundle):
    """What the user came for, straight under the question box."""
    answer = bundle["answer"]
    st.subheader("Answer")
    with st.container(border=True):
        st.markdown(plain_text(answer["answer"]))
    price = bundle.get("price_result")
    if answer.get("declined"):
        status = ('<div class="ag-status ag-declined"><b>Not fully answered.</b> '
                  "The sources I have could not answer the whole question.</div>")
    elif price and price.get("n_deals"):
        status = (f'<div class="ag-status"><b>Answered</b> from {price["n_deals"]:,} '
                  "past resale deals.</div>")
    else:
        status = '<div class="ag-status"><b>Answered.</b></div>'
    st.markdown(status, unsafe_allow_html=True)
    if price:
        st.markdown(price_strip_html(price), unsafe_allow_html=True)


def show_details(bundle):
    """Extra information, further down the page."""
    st.subheader("More Details")
    price = bundle.get("price_result")
    if price:
        lines = []
        if price.get("note") and price.get("n_deals"):
            lines.append(price["note"])
        lines.append(f"Price data from data.gov.sg HDB resale flat prices, up to "
                     f"{month_name(price.get('data_as_of'))}. These are past sale prices, "
                     "not today's asking prices.")
        for line in lines:
            st.markdown(plain_text(line))

    sources = bundle["answer"].get("sources") or []
    if sources:
        st.markdown("**Sources**")
        for s in sources:
            date = (f"effective {s['effective_date']}" if s.get("effective_date")
                    else "effective date not stated on the page")
            link = s.get("url") or "link unavailable"
            st.markdown(plain_text(f"[{s['n']}] {s.get('title')}, {date}: {link}"))

    with st.expander("How This Answer Was Made"):
        items = []
        for step in bundle.get("steps", []):
            name = STEP_NAMES.get(step["step"], step["step"])
            extra = " (stub data)" if step.get("stub") else ""
            css = ' class="ag-error"' if step.get("error") else ""
            error = (f"<br><small>Error: {html.escape(step['error'])}</small>"
                     if step.get("error") else "")
            items.append(f"<li{css}>{html.escape(name)}{extra}"
                         f"<small>{step.get('seconds', '?')} s</small>{error}</li>")
        st.markdown(f'<ol class="ag-steps">{"".join(items)}</ol>', unsafe_allow_html=True)

        routing = bundle.get("routing") or {}
        if routing.get("reason"):
            st.markdown(f"**Why:** {plain_text(routing['reason'])}")
        st.caption(f"Route: {routing.get('route')}. Premise to check: {routing.get('check_premise')}. "
                   f"Answerable: {routing.get('answerable')}.")
        if price and price.get("filters"):
            st.markdown(f"**What the Price Agent Understood** ({price.get('approach')})")
            st.json(price["filters"])
        if bundle.get("agent_errors"):
            st.error(bundle["agent_errors"])


def show_examples(heading):
    st.markdown(f"**{heading}**")
    cols = st.columns(2)
    for i, example in enumerate(EXAMPLES):
        cols[i % 2].button(example, key=f"example_{i}", on_click=ask_example,
                           args=(example,), width="stretch")


# ---------- the page ----------

def ask_example(example):
    st.session_state["question"] = example
    st.session_state["ask_now"] = True


st.set_page_config(page_title="AskGov SG", page_icon="🏠", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.header("Presenter Settings")
    mode = st.radio("System", [FULL, CHATBOT, DEMO], index=0 if HAS_LLM_KEY else 2)
    approach = st.radio("Price Agent Approach", ["A", "B"],
                        format_func=lambda a: {"A": "A: Filter Tool",
                                               "B": "B: Text-to-SQL"}[a],
                        disabled=mode != FULL)
    if HAS_LLM_KEY:
        st.caption("LLM key detected. Full System and Plain Chatbot use live model calls.")
    else:
        st.caption("Add OPENAI_API_KEY or LLM_API_KEY to .env for live answers. Demo Mode needs no key.")

st.markdown('<div class="ag-header"><h1>AskGov SG</h1>'
            "<p>Ask about HDB resale prices or CPF housing rules. Answers come from official "
            "pages and real resale deals, with the sources shown.</p></div>",
            unsafe_allow_html=True)

with st.form("ask_form", border=False):
    question = st.text_input("Your Question", key="question",
                             placeholder="For example: What did 5-room flats in Bishan go for recently?")
    submitted = st.form_submit_button("Ask", type="primary")

bundle, failed = None, None
ask_now = st.session_state.pop("ask_now", False)
asked = (submitted or ask_now) and question.strip()
if asked:
    with st.spinner("Finding the answer..."):
        try:
            bundle = get_answer(question.strip(), mode, approach)
        except Exception as error:  # shown on the page instead of crashing the demo
            failed = f"{type(error).__name__}: {error}"

if failed:
    st.error(f"The answer could not be produced: {failed}. Check the API key in .env, "
             "or switch to Demo Mode.")
elif asked and bundle is None:
    st.warning("Demo mode only has answers for the first three example questions. "
               "Switch to Full System to ask anything else.")

if bundle is not None:
    show_main(bundle)                        # the answer, right under the question box
    show_details(bundle)                     # extra information, further down
    show_examples("Try Another Question")
else:
    show_examples("Or Try One of These")

st.markdown('<div class="ag-footer">General information only, not financial advice. '
            "Check the official HDB and CPF pages before you decide.</div>",
            unsafe_allow_html=True)
