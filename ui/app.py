"""HomeWise demo interface (P1).

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
import re
import sys
import uuid
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
LOGO_FILE = Path(__file__).parent / "homewise_logo.svg"
DEMO, FULL, CHATBOT = "Demo Mode (Saved Samples)", "Full System", "Plain Chatbot (Baseline)"
CHAT = "Chat (Follow-ups)"
EXAMPLES = [
    "What did 4-room flats in Tampines sell for recently?",
    "Will 4-room flats in Tampines cost more next year?",
    "How much is a 5-room resale flat in Tengah?",
    "Can I use my CPF for a 3-room resale flat in Clementi, and roughly how much would it cost?",
]
SHORT_STEP_NAMES = {
    "router": "Read the question",
    "price_agent": "Checked resale deals",
    "policy_agent": "Searched HDB and CPF pages",
    "synthesis": "Wrote the answer",
    "rewrite": "Read the follow-up",
    "self_check": "Checked the answer",
    "chatbot": "Answered from memory (no sources)",
}
STEP_NAMES = {
    "router": "Worked out what the question needs",
    "price_agent": "Looked up past resale deals",
    "policy_agent": "Searched the HDB and CPF pages",
    "synthesis": "Wrote the answer from what was found",
    "chatbot": "Answered from the model's own memory (no sources)",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;800&family=DM+Sans:wght@400;500;700&display=swap');
html, body, .stMarkdown, p, label, input, textarea, button {
  font-family: 'DM Sans', system-ui, sans-serif;
}
.ag-title, .ag-card h3, .ag-card h4, .ag-serif { font-family: 'Fraunces', Georgia, serif !important; }
[data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded' !important; }
/* Use the whole screen, with little empty space at the top. */
.block-container { max-width: 1240px; padding: 1.5rem 2rem 1.5rem; }
header[data-testid="stHeader"] { height: 0; background: transparent; }
[data-testid="stVerticalBlock"] { gap: .75rem; }

/* Header: logo, name and subtitle, like the title slide */
.ag-hero { display: flex; justify-content: space-between; align-items: center; gap: 1.5rem; }
.ag-brand { display: flex; align-items: center; gap: 1.1rem; }
.ag-brand svg { width: 112px; height: 112px; flex: none; }
.ag-title { font-size: 3.4rem; line-height: 1; font-weight: 800; letter-spacing: -.01em; }
.ag-home { color: #3B2418; }
.ag-wise { color: #D9702A; }
.ag-hero p { font-size: 1.2rem; margin: .3rem 0 0; color: #6B4A36; font-weight: 500; }
.ag-mode { border: 2px solid #D9702A; color: #B85A22; border-radius: 999px; padding: .4rem .9rem;
  font-weight: 700; font-size: .9rem; white-space: nowrap; background: #FFFFFF; }
/* A winding road to a home, like the title slide */
.ag-road { position: relative; height: 48px; margin: .3rem 0 .4rem; }
.ag-road .ag-path { position: absolute; left: 0; top: 0; height: 48px; width: calc(100% - 40px); }
.ag-road .ag-home-end { position: absolute; right: 0; bottom: 0; width: 40px; height: 46px; }

/* Question box and Ask button on one line */
div[data-testid="stTextInput"] div[data-baseweb="input"] { min-height: 3.3rem; border-radius: 12px !important;
  background: #FFFFFF !important; border: 2px solid #E3C7AE !important; box-shadow: 0 2px 8px rgba(59,36,24,.06); }
div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within { border-color: #D9702A !important;
  box-shadow: 0 0 0 4px rgba(232,131,58,.18); }
div[data-testid="stTextInput"] div[data-baseweb="input"] > div,
div[data-testid="stTextInput"] input { background: #FFFFFF !important; }
div[data-testid="stTextInput"] input { font-size: 1.15rem; color: #3B2418; }
div[data-testid="stTextInput"] label p { font-size: 1rem; font-weight: 700; color: #3B2418; }
div[data-testid="stFormSubmitButton"] button { min-height: 3.3rem; border-radius: 12px;
  background: #B85A22; border-color: #B85A22; }
div[data-testid="stFormSubmitButton"] button:hover { background: #9C4A1B; border-color: #9C4A1B; }
div[data-testid="stFormSubmitButton"] button p { font-size: 1.15rem; font-weight: 700; color: #FFFFFF; }
.ag-try { font-size: 1rem; color: #3B2418; font-weight: 700; margin: .4rem 0 .5rem; }

/* Example questions as chips */
div.stButton > button { border-radius: 999px; border: 1px solid #E3C7AE; background: #FFFFFF;
  color: #3B2418; padding: .35rem .9rem; min-height: 2.6rem; line-height: 1.3; font-size: .95rem; }
div.stButton > button:hover { border-color: #D9702A; color: #B85A22; background: #FDF0E4; }
div.stButton > button:focus-visible { outline: 3px solid #E8833A; outline-offset: 2px; }

/* The Live / Plain Chatbot / Demo switch, as a pill toggle at the top right */
.st-key-mode { margin-left: auto; }
.st-key-mode [data-testid="stRadioGroup"] { display: flex; gap: 0 !important; background: #FFFFFF;
  border: 1px solid #E3C7AE; border-radius: 999px; padding: 3px; width: fit-content; margin-left: auto; }
.st-key-mode [data-testid="stRadioOption"] { margin: 0 !important; padding: .35rem .9rem; border-radius: 999px;
  cursor: pointer; }
.st-key-mode [data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-mode [data-testid="stRadioOption"] p { font-size: .9rem; font-weight: 700; color: #8A6A55; margin: 0; }
.st-key-mode [data-testid="stRadioOption"][data-selected="true"] { background: #B85A22; }
.st-key-mode [data-testid="stRadioOption"][data-selected="true"] p { color: #FFFFFF; }
.ag-modenote { font-size: .8rem; color: #9C4A1B; text-align: right; margin-top: .3rem; }

/* Streamlit leftovers: a quiet presenter arrow and a styled details bar */
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { opacity: .25; transition: opacity .2s; }
[data-testid="stSidebarCollapsedControl"]:hover, [data-testid="stExpandSidebarButton"]:hover { opacity: 1; }
div[data-testid="stExpander"] details { background: #FFFFFF; border: 1px solid #F0E2D4 !important;
  border-radius: 14px !important; }
div[data-testid="stExpander"] summary p { font-weight: 700; color: #B85A22; }

/* Cards: white with an orange strip on top, like the slides */
.ag-card { background: #FFFFFF; border: 1px solid #F0E2D4; border-top: 6px solid #E8833A;
  border-radius: 18px; padding: 1.3rem 1.5rem; box-shadow: 0 4px 14px rgba(59,36,24,.06);
  margin-bottom: 1rem; }
.ag-label { font-size: .85rem; letter-spacing: .08em; text-transform: uppercase; color: #D9702A;
  font-weight: 700; margin-bottom: .6rem; }
.ag-answer { font-size: 1.2rem; line-height: 1.6; color: #3B2418; }
.ag-answer b { color: #3B2418; font-weight: 700; }
.ag-headline { font-family: 'Fraunces', Georgia, serif; font-size: 1.55rem; line-height: 1.35;
  font-weight: 600; color: #3B2418; }
.ag-headline b { color: #B85A22; font-weight: 800; }
.ag-more { margin-top: .9rem; }
.ag-more summary { cursor: pointer; color: #B85A22; font-weight: 700; font-size: .95rem; list-style: none; }
.ag-more summary::-webkit-details-marker { display: none; }
.ag-more summary::after { content: " \\25BE"; }
.ag-more[open] summary::after { content: " \\25B4"; }
.ag-more[open] summary { margin-bottom: .5rem; }
.ag-more .ag-answer { font-size: 1.05rem; color: #6B4A36; }
.ag-pill { display: inline-block; border-radius: 999px; padding: .25rem .8rem; font-weight: 700;
  font-size: .95rem; margin-bottom: .8rem; background: #E8F3E6; color: #2F6B2A; }
.ag-pill.ag-declined { background: #FDEBD8; color: #9C4A1B; }
.ag-pill.ag-clarify { background: #EFE7DF; color: #6B4A36; }
.ag-cannot { background: #FFF8EF; border: 1px solid #F3D9B8; border-radius: 12px; padding: .7rem .9rem;
  margin-top: .8rem; font-size: .95rem; color: #3B2418; }
.ag-cannot b { color: #9C4A1B; }
.ag-cannot ul { margin: .3rem 0 0; padding-left: 1.2rem; }
.ag-sources { margin-top: 1rem; padding-top: .8rem; border-top: 1px solid #F0E2D4; font-size: .95rem;
  color: #6B4A36; }
.ag-sources a { color: #B85A22; }

/* Steps as stops along a road that ends at a home */
.ag-journey { position: relative; }
.ag-lane { position: absolute; left: 0; right: 66px; top: 36px; height: 18px; border-radius: 9px;
  background: #F6D3B5; }
.ag-lane::after { content: ""; position: absolute; left: 10px; right: 10px; top: 8px;
  border-top: 2px dashed #8A6A55; }
.ag-stops { position: relative; display: flex; justify-content: space-between; align-items: flex-start; }
.ag-stop { display: flex; flex-direction: column; align-items: center; text-align: center; width: 132px; }
.ag-stop .ag-dot { width: 26px; height: 26px; border-radius: 50%; background: #E8833A;
  border: 5px solid #FFFFFF; box-shadow: 0 0 0 2px #E8833A; margin: 27px 0 .35rem; }
.ag-stop.ag-error .ag-dot { background: #B42318; box-shadow: 0 0 0 2px #B42318; }
.ag-stop b { font-size: .92rem; color: #3B2418; font-weight: 600; line-height: 1.25; }
.ag-stop small { font-size: .8rem; color: #8A6A55; }
.ag-stop.ag-end svg { margin-top: 0; width: 50px; height: 57px; }
.ag-stop.ag-end b { color: #B85A22; margin-top: .3rem; }
.ag-chain { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.ag-chain span { position: relative; background: #FDF0E4; border-radius: 999px; padding: .45rem .9rem .45rem 1.9rem;
  color: #3B2418; font-size: .95rem; }
.ag-chain span::before { content: ""; position: absolute; left: .75rem; top: 50%; width: 10px; height: 10px;
  margin-top: -5px; border-radius: 50%; background: #E8833A; }
.ag-chain span small { color: #8A6A55; margin-left: .3rem; }
.ag-chain span.ag-error { background: #FDECEA; }
.ag-chain i { color: #C9A98C; font-style: normal; font-weight: 700; letter-spacing: -2px; }

/* Price facts */
.ag-source { margin-top: 1rem; padding-top: .8rem; border-top: 1px solid #F0E2D4;
  font-size: .85rem; line-height: 1.45; color: #8A6A55; }
.ag-price .ag-legend, .ag-price .ag-note { margin-bottom: 1rem; }
.ag-price h3 { font-size: 1.4rem !important; margin: 0 !important; color: #3B2418 !important; padding: 0 !important;
  font-weight: 600 !important; }
.ag-scope { color: #8A6A55; font-size: .95rem; margin: .2rem 0 1rem; }
.ag-kpi { font-family: 'Fraunces', Georgia, serif; font-size: 2.8rem; font-weight: 800; color: #B85A22;
  line-height: 1.1; }
.ag-kpi-label { font-size: .95rem; color: #6B4A36; }
.ag-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: .6rem; margin-top: 1.1rem; }
.ag-stat { background: #FDF0E4; border-radius: 12px; padding: .6rem .7rem; }
.ag-stat div { font-size: .8rem; color: #8A6A55; }
.ag-stat b { font-size: 1.1rem; color: #3B2418; }
.ag-track { position: relative; height: 10px; border-radius: 5px;
  background: linear-gradient(90deg, #F6D3B5, #C99273); margin: 1.3rem .3rem .3rem; }
.ag-mark { position: absolute; top: -5px; width: 4px; height: 20px; border-radius: 2px;
  transform: translateX(-50%); }
.ag-mark.ag-median { background: #3B2418; }
.ag-mark.ag-mean { background: #E8833A; }
.ag-legend { font-size: .85rem; color: #6B4A36; margin-top: .5rem; }
.ag-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin: 0 .3rem 0 .8rem; vertical-align: middle; }
.ag-note { font-size: .95rem; color: #6B4A36; margin-top: .6rem; }
.ag-few { color: #9C4A1B; }

/* Steps in the details */
.ag-steps { list-style: none; padding: 0; margin: .25rem 0 0; }
.ag-steps li { position: relative; padding: 0 0 1rem 1.6rem; color: #3B2418; }
.ag-steps li::before { content: ""; position: absolute; left: 4px; top: .35rem; width: 10px;
  height: 10px; border-radius: 50%; background: #E8833A; }
.ag-steps li::after { content: ""; position: absolute; left: 8px; top: 1.1rem; bottom: -.2rem;
  width: 2px; border-left: 2px dashed #C9A98C; }
.ag-steps li:last-child::after { display: none; }
.ag-steps li.ag-error::before { background: #B42318; }
.ag-steps small { color: #8A6A55; margin-left: .35rem; }

/* Start screen */
.ag-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
.ag-feature h4 { margin: 0 0 .35rem !important; font-size: 1.35rem !important; color: #3B2418 !important;
  padding: 0 !important; font-weight: 600 !important; }
.ag-feature p { margin: 0; color: #6B4A36; font-size: 1rem; line-height: 1.5; }
.ag-feature .ag-eg { margin-top: .6rem; font-style: italic; color: #B85A22; }
.ag-flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin-top: .3rem; }
.ag-flow div { background: #FDF0E4; border-radius: 14px; padding: .8rem 1rem; color: #3B2418;
  font-size: .98rem; line-height: 1.4; }
.ag-flow b { display: block; color: #B85A22; font-size: .85rem; letter-spacing: .05em;
  text-transform: uppercase; margin-bottom: .2rem; }
.ag-footer { font-size: .85rem; color: #8A6A55; margin-top: .5rem; text-align: center; }

@media (max-width: 760px) { .ag-grid, .ag-flow { grid-template-columns: 1fr; }
  .ag-hero { flex-direction: column; align-items: flex-start; } .ag-title { font-size: 2.4rem; }
  .ag-brand svg { width: 60px; height: 60px; } .ag-stats { grid-template-columns: 1fr 1fr; } }
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


# ---------- chat mode (follow-up questions, from the chat page) ----------

def show_chat():
    """The Chat button: P3's chat from ui/chat_app.py, inside this page. Each answer
    stays on screen and follow-ups are asked underneath; chats are saved and listed
    in the sidebar."""
    from chat_view import (CHAT_CSS, ask, chat_graph, chat_history, plain_text, saved_chats,
                           short, show_answer, show_details)
    st.markdown(f"<style>{CHAT_CSS}</style>", unsafe_allow_html=True)
    app, connection = chat_graph()
    if "thread_id" not in st.session_state:
        st.session_state["thread_id"] = uuid.uuid4().hex

    with st.sidebar:
        st.divider()
        if st.button("New Chat", type="primary", width="stretch"):
            st.session_state["thread_id"] = uuid.uuid4().hex
            st.rerun()
        st.header("Chats")
        chats = saved_chats(app, connection)
        if not chats:
            st.caption("No saved chats yet.")
        for chat_id, title in chats:
            current = chat_id == st.session_state["thread_id"]
            if st.button(short(title), key=f"chat_{chat_id}", width="stretch",
                         disabled=current, help=title):
                st.session_state["thread_id"] = chat_id
                st.rerun()
        st.caption("Your chats are saved on this computer.")

    thread_id = st.session_state["thread_id"]
    turns = chat_history(app, thread_id)
    if not turns:
        st.markdown('<div class="ag-try">Ask about HDB resale prices or CPF housing rules, '
                    "then keep asking.</div>", unsafe_allow_html=True)
        show_examples()
    for turn in turns:
        with st.chat_message("user"):
            st.markdown(plain_text(turn["user_question"]))
        with st.chat_message("assistant"):
            show_answer(turn)
            show_details(turn)

    question = st.chat_input("Ask a question, or a follow-up")
    if not question and st.session_state.pop("ask_now", False):
        question = st.session_state.get("question")
    if question and question.strip():
        with st.chat_message("user"):
            st.markdown(plain_text(question.strip()))
        with st.chat_message("assistant"):
            with st.spinner("Finding the answer..."):
                try:
                    ask(app, thread_id, question.strip())
                except Exception as error:  # shown on the page instead of crashing the demo
                    st.error(f"The answer could not be produced: {type(error).__name__}: {error}. "
                             "Check the API key in .env, or switch to Demo.")
                    return
        st.rerun()  # redraw the chat from the saved history, and add it to the sidebar


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


def safe(text):
    """Text placed inside our own HTML: escaped, and $ kept as a plain dollar sign."""
    return html.escape(str(text)).replace("$", "&#36;")


def status_pill(bundle):
    answer, price = bundle["answer"], bundle.get("price_result")
    if answer.get("needs_clarification"):
        return '<span class="ag-pill ag-clarify">Need more detail</span>'
    if answer.get("declined"):
        return '<span class="ag-pill ag-declined">Not fully answered</span>'
    if price and price.get("n_deals"):
        return f'<span class="ag-pill">Answered from {price["n_deals"]:,} past resale deals</span>'
    return '<span class="ag-pill">Answered</span>'


def highlight(text):
    """Bold the key facts in an answer: prices, and how many deals or flats it is based on."""
    text = re.sub(r"&#36;\d{1,3}(?:,\d{3})*", lambda m: f"<b>{m.group(0)}</b>", text)
    return re.sub(r"\b\d{1,3}(?:,\d{3})*(?= (?:\d-room )?(?:resale )?(?:flats|deals))",
                  lambda m: f"<b>{m.group(0)}</b>", text)


def price_line(price):
    """'3-room flats in Clementi sold for a median of $434,000 from Oct 2025 to Sep 2026.'"""
    months = ""
    if price.get("period_start") and price.get("period_end"):
        months = f" from {month_name(price['period_start'])} to {month_name(price['period_end'])}"
    ft, town = price.get("flat_type"), price.get("town")
    flats = "Flats" if ft == "ALL" else f"{nice(ft)} flats"
    where = "across Singapore" if town == "ALL" else f"in {nice(town)}"
    return f"{flats[0].upper() + flats[1:]} {where} sold for a median of {money(price['median_price'])}{months}."


def opening_line(text):
    """The answer's opening sentence, without citation marks. A bare 'Yes.' or 'No.'
    takes the main clause of the next sentence, so the line still says something."""
    text = re.sub(r"\s*\[\d+\]", "", str(text)).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    first = sentences[0] if sentences else ""
    if len(first.split()) <= 2 and len(sentences) > 1:
        clause = sentences[1].split(",")[0].rstrip(".!? ")
        first = f"{first.rstrip('.!')}, {clause[0].lower() + clause[1:]}." if clause else first
    return first


def headline(bundle):
    """One line that answers the question; the full answer sits behind 'Read the full answer'.
    A price question gets the price figures, a rules question the answer's opening, and a
    question about both gets the opening followed by the price figures."""
    answer, price = bundle["answer"], bundle.get("price_result") or {}
    route = (bundle.get("routing") or {}).get("route")
    has_figures = (not answer.get("declined") and price.get("n_deals")
                   and price.get("median_price") is not None)
    if has_figures and route == "both":
        return f"{opening_line(answer['answer'])} {price_line(price)}"
    if has_figures:
        return price_line(price)
    return opening_line(answer["answer"])


def answer_card_html(bundle):
    """The answer in one line, with the full answer one click away."""
    answer = bundle["answer"]
    short, full = headline(bundle), str(answer["answer"]).strip()
    parts = ['<div class="ag-card">', '<div class="ag-label">Answer</div>', status_pill(bundle),
             f'<div class="ag-headline">{highlight(safe(short))}</div>']
    cannot = answer.get("cannot_answer") or []
    if cannot:
        items = "".join(f"<li>{safe(c.get('part', ''))}: {safe(c.get('reason', ''))}</li>" for c in cannot)
        parts.append(f'<div class="ag-cannot"><b>Can&#39;t answer</b><ul>{items}</ul></div>')
    if full and full != short:
        parts.append('<details class="ag-more"><summary>Read the full answer</summary>'
                     f'<div class="ag-answer">{highlight(safe(full))}</div></details>')
    sources = answer.get("sources") or []
    if sources:
        items = []
        for s in sources:
            title = safe(s.get("title") or "Source")
            link = (f'<a href="{html.escape(s["url"])}" target="_blank">{title}</a>'
                    if s.get("url") else title)
            items.append(f"[{s.get('n')}] {link}")
        parts.append('<div class="ag-sources"><b>Sources</b><br>' + "<br>".join(items) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def price_card_html(price):
    """The key figures: the median in large type, then average, lowest and highest."""
    period = f"{month_name(price.get('period_start'))} to {month_name(price.get('period_end'))}"
    n = price.get("n_deals") or 0
    parts = ['<div class="ag-card ag-price" role="group" aria-label="Price facts">',
             '<div class="ag-label">Price Facts</div>',
             f"<h3>{safe(flat_and_town(price))}</h3>",
             f'<div class="ag-scope">{period} &middot; {n:,} resale deal{"s" if n != 1 else ""}</div>']

    low, high = price.get("min_price"), price.get("max_price")
    if n and low is not None and high is not None:
        med, mean = price.get("median_price"), price.get("mean_price")
        parts += [
            '<div class="ag-kpi-label">Median Price</div>',
            f'<div class="ag-kpi">{money(med)}</div>',
            '<div class="ag-stats">',
            f"<div class='ag-stat'><div>Average</div><b>{money(mean)}</b></div>",
            f"<div class='ag-stat'><div>Lowest Deal</div><b>{money(low)}</b></div>",
            f"<div class='ag-stat'><div>Highest Deal</div><b>{money(high)}</b></div>",
            "</div>",
            '<div class="ag-track">',
            f'<div class="ag-mark ag-median" style="left:{position(med, low, high):.1f}%"></div>',
            f'<div class="ag-mark ag-mean" style="left:{position(mean, low, high):.1f}%"></div>',
            "</div>",
            '<div class="ag-legend">Lowest to highest deal'
            '<i style="background:#3B2418"></i>Median<i style="background:#E8833A"></i>Average</div>',
        ]
        if n < 10:
            parts.append('<div class="ag-note ag-few">Based on fewer than 10 sales, '
                         "so treat these figures with care.</div>")
    elif price.get("note"):
        # No figures to show: the reason belongs here, not in the details.
        parts.append(f'<div class="ag-note">{safe(price["note"])}</div>')
    if price.get("stub"):
        parts.append('<div class="ag-note ag-few">Stub data: not real prices.</div>')
    parts.append(f'<div class="ag-source">Source: HDB resale flat prices, data.gov.sg, up to '
                 f"{month_name(price.get('data_as_of'))}. Past sale prices, not today&#39;s asking prices.</div>")
    parts.append("</div>")
    return "".join(parts).replace("$", "&#36;")


BUILDING_SVG = (
    '<svg viewBox="0 0 64 72" width="58" height="66" role="img" aria-label="Your home">'
    '<rect x="6" y="10" width="52" height="62" rx="5" fill="#E8833A"/>'
    '<rect x="2" y="6" width="60" height="7" rx="3" fill="#B85A22"/>'
    '<rect x="14" y="17" width="36" height="9" rx="2" fill="#FEF6EE"/>'
    '<text x="32" y="24.5" font-size="7" font-family="DM Sans, sans-serif" font-weight="700" '
    'text-anchor="middle" fill="#3B2418">HDB</text>'
    '<rect x="14" y="32" width="9" height="8" rx="1.5" fill="#FEF6EE"/>'
    '<rect x="27.5" y="32" width="9" height="8" rx="1.5" fill="#FEF6EE"/>'
    '<rect x="41" y="32" width="9" height="8" rx="1.5" fill="#FEF6EE"/>'
    '<rect x="14" y="46" width="9" height="8" rx="1.5" fill="#FEF6EE"/>'
    '<rect x="41" y="46" width="9" height="8" rx="1.5" fill="#FEF6EE"/>'
    '<rect x="26" y="56" width="12" height="16" rx="2" fill="#FEF6EE"/>'
    "</svg>"
)


ROAD_HTML = (
    '<div class="ag-road" aria-hidden="true">'
    '<svg class="ag-path" viewBox="0 0 1200 48" preserveAspectRatio="none">'
    '<path d="M0 28 C 120 8, 230 8, 340 24 S 560 44, 680 26 S 900 8, 1020 24 S 1140 44, 1200 40" '
    'fill="none" stroke="#F6D3B5" stroke-width="11" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
    '<path d="M0 28 C 120 8, 230 8, 340 24 S 560 44, 680 26 S 900 8, 1020 24 S 1140 44, 1200 40" '
    'fill="none" stroke="#B98A6E" stroke-width="1.5" stroke-dasharray="6 6" vector-effect="non-scaling-stroke"/>'
    "</svg>"
    + BUILDING_SVG.replace('width="58" height="66"', 'class="ag-home-end" width="40" height="46"')
    + "</div>"
)


def chain_html(bundle):
    """The steps as stops along a road that ends at a home, like the title slide."""
    stops = []
    for step in bundle.get("steps", []):
        name = SHORT_STEP_NAMES.get(step["step"], step["step"])
        css = " ag-error" if step.get("error") else ""
        stops.append(f'<div class="ag-stop{css}"><span class="ag-dot"></span>'
                     f"<b>{html.escape(name)}</b><small>{step.get('seconds', '?')} s</small></div>")
    stops.append(f'<div class="ag-stop ag-end">{BUILDING_SVG}<b>Answer is ready</b></div>')
    return ('<div class="ag-card"><div class="ag-label">How This Answer Was Made</div>'
            '<div class="ag-journey"><div class="ag-lane"></div>'
            f'<div class="ag-stops">{"".join(stops)}</div></div></div>')


def show_main(bundle):
    """What the user came for: the answer beside the price facts, on the first screen."""
    price = bundle.get("price_result")
    if price and price.get("n_deals"):
        # Figures to show: the answer beside the price facts. Each box is as tall as its content.
        left, right = st.columns([3, 2], gap="medium")
        left.markdown(answer_card_html(bundle) + chain_html(bundle), unsafe_allow_html=True)
        right.markdown(price_card_html(price), unsafe_allow_html=True)
    else:
        st.markdown(answer_card_html(bundle) + chain_html(bundle), unsafe_allow_html=True)


def steps_html(bundle):
    items = []
    for step in bundle.get("steps", []):
        name = STEP_NAMES.get(step["step"], step["step"])
        extra = " (stub data)" if step.get("stub") else ""
        css = ' class="ag-error"' if step.get("error") else ""
        error = (f"<br><small>Error: {html.escape(step['error'])}</small>"
                 if step.get("error") else "")
        items.append(f"<li{css}>{html.escape(name)}{extra}"
                     f"<small>{step.get('seconds', '?')} s</small>{error}</li>")
    return f'<ol class="ag-steps">{"".join(items)}</ol>'


def show_details(bundle):
    """Extra information, below the main answer."""
    price = bundle.get("price_result")
    routing = bundle.get("routing") or {}
    with st.expander("Behind the Scenes: Steps, Route and Data", expanded=False):
        left, right = st.columns(2, gap="large")
        with left:
            st.markdown("**Steps**")
            st.markdown(steps_html(bundle), unsafe_allow_html=True)
            if routing.get("reason"):
                st.markdown(f"**Why this route:** {plain_text(routing['reason'])}")
            st.caption(f"Route: {routing.get('route')}. Premise to check: "
                       f"{routing.get('check_premise')}. Answerable: {routing.get('answerable')}.")
        with right:
            st.markdown("**About the Data**")
            if price:
                if price.get("note") and price.get("n_deals"):
                    st.markdown(plain_text(price["note"]))
                st.markdown(plain_text(
                    f"HDB resale flat prices from data.gov.sg, up to "
                    f"{month_name(price.get('data_as_of'))}. These are past sale prices, "
                    "not today's asking prices."))
                if price.get("filters"):
                    st.markdown(f"**What the Price Agent Understood** ({price.get('approach')})")
                    st.json(price["filters"], expanded=False)
            for s in bundle["answer"].get("sources") or []:
                date = (f"effective {s['effective_date']}" if s.get("effective_date")
                        else "effective date not stated on the page")
                st.markdown(plain_text(f"[{s['n']}] {s.get('title')}, {date}"))
        if bundle.get("agent_errors"):
            st.error(bundle["agent_errors"])


def show_examples():
    st.markdown('<div class="ag-try">Try an Example</div>', unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES))
    for i, (col, example) in enumerate(zip(cols, EXAMPLES)):
        col.button(SHORT_EXAMPLES[i], key=f"example_{i}", on_click=ask_example,
                   args=(example,), width="stretch")


# ---------- the page ----------

SHORT_EXAMPLES = [
    "4-room in Tampines, recently",
    "Tampines prices next year?",
    "5-room in Tengah",
    "CPF for a 3-room in Clementi",
]


START_HTML = (
    '<div class="ag-grid">'
    '<div class="ag-card ag-feature"><div class="ag-label">Prices</div><h4>What flats really sold for</h4>'
    "<p>Median, average, lowest and highest prices from past HDB resale deals.</p>"
    '<p class="ag-eg">"What did 4-room flats in Tampines sell for recently?"</p></div>'
    '<div class="ag-card ag-feature"><div class="ag-label">Rules</div><h4>HDB and CPF rules</h4>'
    "<p>Answers from the official HDB and CPF pages, with the source shown.</p>"
    '<p class="ag-eg">"Can I use my CPF for a resale flat?"</p></div>'
    '<div class="ag-card ag-feature"><div class="ag-label">Both</div><h4>Prices and rules together</h4>'
    "<p>One question, one answer that combines real prices with the rules that apply.</p>"
    '<p class="ag-eg">"CPF for a 3-room in Clementi, and the price?"</p></div>'
    "</div>"
    '<div class="ag-label" style="margin-top:1.2rem">How It Works</div>'
    '<div class="ag-flow"><div><b>1. Ask</b>Type a question in your own words.</div>'
    "<div><b>2. Route</b>The supervisor decides if it needs prices, rules or both.</div>"
    "<div><b>3. Look up</b>The agents check real resale deals and official pages.</div>"
    "<div><b>4. Answer</b>You get one answer, with the facts and sources behind it.</div></div>"
)


def ask_example(example):
    st.session_state["question"] = example
    st.session_state["ask_now"] = True


st.set_page_config(page_title="HomeWise", page_icon="🏠", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

logo_svg = LOGO_FILE.read_text(encoding="utf-8") if LOGO_FILE.exists() else ""
brand_col, mode_col = st.columns([3, 1], vertical_alignment="center")
brand_col.markdown(
    f'<div class="ag-hero"><div class="ag-brand">{logo_svg}<div>'
    '<div class="ag-title"><span class="ag-home">Home</span><span class="ag-wise">Wise</span></div>'
    "<p>Your guide to smarter HDB resale decisions</p>"
    "</div></div></div>",
    unsafe_allow_html=True)
with mode_col:
    # The presenter's switch: live answers, the plain chatbot baseline, or saved demo answers.
    mode = st.radio("Mode", [FULL, CHAT, DEMO], index=0 if HAS_LLM_KEY else 2, horizontal=True,
                    format_func=lambda m: {FULL: "Live", CHAT: "Chat", DEMO: "Demo"}[m],
                    label_visibility="collapsed", key="mode")
    if mode != DEMO and not HAS_LLM_KEY:
        st.markdown('<div class="ag-modenote">No API key found, so live answers will fail. '
                    "Use Demo.</div>", unsafe_allow_html=True)
st.markdown(ROAD_HTML, unsafe_allow_html=True)

with st.sidebar:
    st.header("Presenter Settings")
    approach = st.radio("Price Agent Approach", ["A", "B"],
                        format_func=lambda a: {"A": "A: Filter Tool",
                                               "B": "B: Text-to-SQL"}[a],
                        disabled=mode != FULL)
    if HAS_LLM_KEY:
        st.caption("LLM key detected. Live and Chat use live model calls.")
    else:
        st.caption("Add OPENAI_API_KEY or LLM_API_KEY to .env for live answers. Demo needs no key.")

if mode == CHAT:
    show_chat()
else:
    with st.form("ask_form", border=False):
        q_col, b_col = st.columns([6, 1], vertical_alignment="bottom")
        question = q_col.text_input("Your Question", key="question",
                                    placeholder="For example: What did 5-room flats in Bishan go for recently?")
        submitted = b_col.form_submit_button("Ask", type="primary", width="stretch")

    show_examples()

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
        show_main(bundle)       # answer and price facts side by side, on the first screen
        show_details(bundle)    # how it was made, one click away
    elif not asked:
        st.markdown(START_HTML, unsafe_allow_html=True)

st.markdown('<div class="ag-footer">General information only, not financial advice. '
            "Check the official HDB and CPF pages before you decide.</div>",
            unsafe_allow_html=True)
