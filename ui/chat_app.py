"""HomeWise chat interface (P3; HomeWise look by P1).

A chat version of P1's demo page (ui/app.py), running P3's LangGraph graph
with memory. Every chat is a LangGraph thread saved in a local SQLite file,
so you can start a new chat, switch back to an earlier one and keep asking.
Each turn keeps its own analysis: answer, price facts, sources, the steps
taken (including the self check), and that turn's cost.

Run from the project root:
    streamlit run ui/chat_app.py

The display helpers are copied from ui/app.py (importing that file would
run its whole page), with a self check step and verdict added.
"""

import html
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

from agents.graph.graph import CHAT_DB  # noqa: E402  (needs PROJECT_ROOT on sys.path)

STEP_NAMES = {
    "rewrite": "Read the follow-up in the context of this chat",
    "router":"Worked out what the question needs",
    "price_agent": "Looked up past resale deals",
    "policy_agent": "Searched the HDB and CPF pages",
    "synthesis": "Wrote the answer from what was found",
    "self_check": "Checked the answer against the answer rules",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;800&family=DM+Sans:wght@400;500;700&display=swap');
html, body, .stMarkdown, p, label, input, textarea, button {
  font-family: 'DM Sans', system-ui, sans-serif;
}
[data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded' !important; }
.block-container, [data-testid="stMainBlockContainer"] { max-width: 860px; padding-top: 3rem !important; }

/* Header: logo and name, like the title slide and the main page */
.ag-header { display: flex; align-items: center; gap: 1rem; margin-bottom: .2rem; }
.ag-header svg { width: 84px; height: 84px; flex: none; }
.ag-title { font-family: 'Fraunces', Georgia, serif; font-size: 2.7rem; line-height: 1; font-weight: 800; }
.ag-home { color: #3B2418; } .ag-wise { color: #D9702A; }
.ag-header p { font-size: 1.05rem; color: #6B4A36; margin: .35rem 0 0; }
.ag-road { position: relative; height: 40px; margin: .2rem 0 .8rem; }
.ag-road svg { position: absolute; left: 0; top: 0; width: 100%; height: 40px; }

/* Chat bubbles as white cards */
[data-testid="stChatMessage"] { background: #FFFFFF; border: 1px solid #F0E2D4; border-radius: 18px;
  padding: 1rem 1.1rem; box-shadow: 0 4px 14px rgba(59,36,24,.05); }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: #FDF0E4; }
[data-testid="stChatMessageAvatarAssistant"] { background: #E8833A !important; }
[data-testid="stChatMessageAvatarUser"] { background: #3B2418 !important; }
[data-testid="stChatInput"] { border: 2px solid #E3C7AE !important; border-radius: 14px !important;
  background: #FFFFFF !important; }
[data-testid="stChatInput"]:focus-within { border-color: #D9702A !important; }
[data-testid="stChatInputSubmitButton"] { background: #B85A22 !important; color: #FFFFFF !important; }

/* Sidebar chat list */
section[data-testid="stSidebar"] button { border-radius: 999px; }
section[data-testid="stSidebar"] h2 { font-family: 'Fraunces', Georgia, serif; color: #3B2418; }

.ag-status { font-size: .95rem; color: #6B4A36; margin: .5rem 0 .5rem; }
.ag-status b { color: #2F6B2A; }
.ag-status.ag-declined b { color: #9C4A1B; }
.ag-status.ag-clarify b { color: #6B4A36; }
.ag-rewrite { font-size: .9rem; color: #8A6A55; margin-bottom: .4rem; }
.ag-headline { font-family: 'Fraunces', Georgia, serif; font-size: 1.35rem; line-height: 1.35;
  font-weight: 600; color: #3B2418; }
.ag-headline b { color: #B85A22; font-weight: 800; }
.ag-more { margin-top: .6rem; }
.ag-more summary { cursor: pointer; color: #B85A22; font-weight: 700; font-size: .95rem; list-style: none; }
.ag-more summary::-webkit-details-marker { display: none; }
.ag-more summary::after { content: " \\25BE"; }
.ag-more[open] summary::after { content: " \\25B4"; }
.ag-more[open] summary { margin-bottom: .4rem; }
.ag-answer { font-size: 1rem; line-height: 1.6; color: #6B4A36; }
.ag-answer b { color: #3B2418; }

.ag-cannot { background: #FFF8EF; border: 1px solid #F3D9B8; border-radius: 12px;
  padding: .7rem .9rem; margin: .6rem 0; font-size: .95rem; color: #3B2418; }
.ag-cannot b { color: #9C4A1B; }
.ag-cannot ul { margin: .3rem 0 0; padding-left: 1.2rem; }

/* Price facts as a card with an orange strip on top */
.ag-strip { background: #FFFFFF; border: 1px solid #F0E2D4; border-top: 6px solid #E8833A;
  border-radius: 16px; padding: 1.1rem 1.25rem 1.4rem; margin: 1rem 0; }
.ag-strip h3 { font-family: 'Fraunces', Georgia, serif !important; font-size: 1.15rem !important;
  font-weight: 600 !important; margin: 0 0 .2rem !important; padding: 0 !important; color: #3B2418 !important; }
.ag-strip .ag-scope { color: #8A6A55; font-size: .95rem; margin-bottom: .3rem; }
.ag-track { position: relative; height: 10px; border-radius: 5px;
  background: linear-gradient(90deg, #F6D3B5, #C99273); margin: 2.6rem .5rem 0; }
.ag-mark { position: absolute; top: -6px; width: 4px; height: 22px; border-radius: 2px;
  transform: translateX(-50%); }
.ag-mark.ag-median { background: #3B2418; }
.ag-mark.ag-mean { background: #E8833A; }
.ag-mark span { position: absolute; bottom: 28px; left: 50%; transform: translateX(-50%);
  white-space: nowrap; font-size: .9rem; color: #3B2418; font-weight: 700; }
.ag-mark.ag-mean span { bottom: auto; top: 28px; color: #B85A22; }
.ag-ends { display: flex; justify-content: space-between; margin-top: 2.4rem;
  font-size: .9rem; color: #8A6A55; }
.ag-ends b { color: #3B2418; font-size: 1.05rem; }
.ag-note { font-size: .9rem; color: #6B4A36; margin-top: .8rem; }
.ag-few { color: #9C4A1B; }

/* Steps as stops along a dashed road */
.ag-steps { list-style: none; padding: 0; margin: .25rem 0 0; }
.ag-steps li { position: relative; padding: 0 0 1rem 1.6rem; color: #3B2418; }
.ag-steps li::before { content: ""; position: absolute; left: 4px; top: .35rem; width: 10px;
  height: 10px; border-radius: 50%; background: #E8833A; }
.ag-steps li::after { content: ""; position: absolute; left: 8px; top: 1.1rem; bottom: -.2rem;
  border-left: 2px dashed #C9A98C; }
.ag-steps li:last-child::after { display: none; }
.ag-steps li.ag-error::before { background: #B42318; }
.ag-steps li.ag-weak::before { background: #D9A441; }
.ag-steps small { color: #8A6A55; margin-left: .35rem; }
div[data-testid="stExpander"] details { background: #FFFFFF; border: 1px solid #F0E2D4 !important;
  border-radius: 14px !important; }
div[data-testid="stExpander"] summary p { font-weight: 700; color: #B85A22; }
.ag-footer { font-size: .85rem; color: #8A6A55; margin-top: 2rem; text-align: center; }

@media (max-width: 640px) { .ag-title { font-size: 2rem; } .ag-header svg { width: 60px; height: 60px; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
"""

LOGO_FILE = Path(__file__).parent / "homewise_logo.svg"
ROAD_SVG = (
    '<svg viewBox="0 0 860 40" preserveAspectRatio="none" aria-hidden="true">'
    '<path d="M0 24 C 90 6, 170 6, 250 20 S 410 36, 490 22 S 650 6, 730 20 S 820 34, 860 30" '
    'fill="none" stroke="#F6D3B5" stroke-width="10" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
    '<path d="M0 24 C 90 6, 170 6, 250 20 S 410 36, 490 22 S 650 6, 730 20 S 820 34, 860 30" '
    'fill="none" stroke="#B98A6E" stroke-width="1.5" stroke-dasharray="6 6" vector-effect="non-scaling-stroke"/>'
    "</svg>"
)



# ---------- the graph and its memory ----------

@st.cache_resource
def chat_graph():
    """One graph per app process, saving every chat to CHAT_DB."""
    from agents.graph.graph import build_graph, chat_memory

    saver = chat_memory()
    return build_graph(checkpointer=saver), saver.conn


def thread_config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def chat_history(app, thread_id):
    """The finished turns of one chat (empty for a new chat)."""
    return app.get_state(thread_config(thread_id)).values.get("history") or []


def saved_chats(app, connection):
    """(thread_id, title) for every saved chat, most recently used first.
    Checkpoint IDs increase over time, so the latest one orders the chats."""
    rows = connection.execute(
        "SELECT thread_id FROM checkpoints GROUP BY thread_id "
        "ORDER BY MAX(checkpoint_id) DESC").fetchall()
    chats = []
    for (thread_id,) in rows:
        history = chat_history(app, thread_id)
        if history:
            chats.append((thread_id, history[0]["user_question"]))
    return chats


def ask(app, thread_id, question):
    """Decomposition is on for chat: follow-ups are often comparisons ("compare
    the two"), and the price agent looks up one town per task."""
    from agents.graph.graph import run
    run(question, app=app, thread_id=thread_id, decompose=True)


def price_results(turn):
    """Every price lookup in the turn: one per task with decomposition, else one."""
    tasks = [r["result"] for r in turn.get("task_results") or []
             if r["task"]["agent"] == "price" and r.get("result")]
    return tasks or ([turn["price_result"]] if turn.get("price_result") else [])


# ---------- small formatting helpers (from ui/app.py) ----------

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


def safe(text):
    """Text placed inside our own HTML: escaped, and $ kept as a plain dollar sign."""
    return html.escape(str(text)).replace("$", "&#36;")


def highlight(text):
    """Bold the key facts in an answer: prices, and how many deals or flats it is based on."""
    text = re.sub(r"&#36;\d{1,3}(?:,\d{3})*", lambda m: f"<b>{m.group(0)}</b>", text)
    return re.sub(r"\b\d{1,3}(?:,\d{3})*(?= (?:\d-room )?(?:resale )?(?:flats|deals))",
                  lambda m: f"<b>{m.group(0)}</b>", text)


def opening_line(text):
    """The answer's opening sentence, without citation marks (same rule as ui/app.py)."""
    text = re.sub(r"\s*\[\d+\]", "", str(text)).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    first = sentences[0] if sentences else ""
    if len(first.split()) <= 2 and len(sentences) > 1:
        clause = sentences[1].split(",")[0].rstrip(".!? ")
        first = f"{first.rstrip('.!')}, {clause[0].lower() + clause[1:]}." if clause else first
    return first


def headline(answer, prices, route=None):
    """One line that answers the question (same rule as ui/app.py). With one price lookup
    it uses the figures; a question about prices and rules gets the opening plus the figures;
    otherwise the answer's opening sentence."""
    with_deals = [p for p in prices if p.get("n_deals") and p.get("median_price") is not None]
    if not answer.get("declined") and len(prices) == 1 and with_deals:
        p = with_deals[0]
        ft, town = p.get("flat_type"), p.get("town")
        flats = "Flats" if ft == "ALL" else f"{nice(ft)} flats"
        where = "across Singapore" if town == "ALL" else f"in {nice(town)}"
        months = ""
        if p.get("period_start") and p.get("period_end"):
            months = f" from {month_name(p['period_start'])} to {month_name(p['period_end'])}"
        line = f"{flats[0].upper() + flats[1:]} {where} sold for a median of {money(p['median_price'])}{months}."
        return f"{opening_line(answer['answer'])} {line}" if route == "both" else line
    return opening_line(answer["answer"])


def short(text, limit=40):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------- one turn's analysis (from ui/app.py) ----------

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
        parts.append(f'<div class="ag-note">{html.escape(price["note"])}</div>')
    parts.append("</div>")
    return "".join(parts).replace("$", "&#36;")


def show_answer(turn):
    """The answer, its status line and the price strip."""
    answer = turn["answer"]
    if turn["question"] != turn["user_question"]:
        st.markdown(f'<div class="ag-rewrite">Understood as: <i>{html.escape(turn["question"])}'
                    "</i></div>", unsafe_allow_html=True)
    prices = price_results(turn)
    route = (turn.get("routing") or {}).get("route")
    one_line, full = headline(answer, prices, route), str(answer["answer"]).strip()
    more = ""
    if full and full != one_line:
        more = ('<details class="ag-more"><summary>Read the full answer</summary>'
                f'<div class="ag-answer">{highlight(safe(full))}</div></details>')
    st.markdown(f'<div class="ag-headline">{highlight(safe(one_line))}</div>{more}',
                unsafe_allow_html=True)
    price = prices[0] if prices else None
    if answer.get("needs_clarification"):
        status = ('<div class="ag-status ag-clarify"><b>Need more detail.</b> '
                  "The question is too unclear to search the right sources yet.</div>")
    elif answer.get("declined"):
        status = ('<div class="ag-status ag-declined"><b>Not fully answered.</b> '
                  "The sources I have could not answer the whole question.</div>")
    elif price and price.get("n_deals"):
        n_deals = sum(p.get("n_deals") or 0 for p in prices)
        status = (f'<div class="ag-status"><b>Answered</b> from {n_deals:,} '
                  "past resale deals.</div>")
    else:
        status = '<div class="ag-status"><b>Answered.</b></div>'
    st.markdown(status, unsafe_allow_html=True)
    cannot_answer = answer.get("cannot_answer") or []
    if cannot_answer:
        items = "".join(
            f"<li>{html.escape(item['part'])}: {html.escape(item['reason'])}</li>"
            for item in cannot_answer
        )
        st.markdown(f'<div class="ag-cannot"><b>Can\'t answer</b><ul>{items}</ul></div>',
                    unsafe_allow_html=True)
    for price in prices:
        st.markdown(price_strip_html(price), unsafe_allow_html=True)


def steps_html(steps):
    items = []
    for step in steps:
        name = STEP_NAMES.get(step["step"], step["step"])
        css, extra = "", ""
        if step.get("error"):
            css, extra = ' class="ag-error"', f"<br><small>Error: {html.escape(step['error'])}</small>"
        elif step.get("verdict") == "weak":
            retry = ", ".join(step.get("retry") or []) or "nothing (no retries left)"
            css, extra = ' class="ag-weak"', f"<br><small>Weak; sent back to: {html.escape(retry)}</small>"
        elif step.get("verdict") == "pass":
            extra = "<br><small>Passed</small>"
        elif step["step"] == "rewrite":
            extra = ("<br><small>Rewritten as a standalone question</small>" if step.get("changed")
                     else "<br><small>Already standalone; unchanged</small>")
        items.append(f"<li{css}>{html.escape(name)}"
                     f"<small>{step.get('seconds', '?')} s</small>{extra}</li>")
    return f'<ol class="ag-steps">{"".join(items)}</ol>'


def show_details(turn):
    """Sources, the steps taken and why: the same analysis as ui/app.py, per turn."""
    prices = price_results(turn)
    price = prices[0] if prices else None
    sources = turn["answer"].get("sources") or []
    if sources:
        st.markdown("**Sources**")
        for s in sources:
            date = (f"effective {s['effective_date']}" if s.get("effective_date")
                    else "effective date not stated on the page")
            link = s.get("url") or "link unavailable"
            st.markdown(plain_text(f"[{s['n']}] {s.get('title')}, {date}: {link}"))

    with st.expander("How This Answer Was Made"):
        if price:
            if price.get("note") and price.get("n_deals"):
                st.markdown(plain_text(price["note"]))
            st.markdown(plain_text(
                f"Price data from data.gov.sg HDB resale flat prices, up to "
                f"{month_name(price.get('data_as_of'))}. These are past sale prices, "
                "not today's asking prices."))
        st.markdown(steps_html(turn.get("steps") or []), unsafe_allow_html=True)

        routing = turn.get("routing") or {}
        if routing.get("reason"):
            st.markdown(f"**Why:** {plain_text(routing['reason'])}")
        st.caption(f"Route: {routing.get('route')}. Premise to check: {routing.get('check_premise')}. "
                   f"Answerable: {routing.get('answerable')}.")
        check = turn.get("self_check") or {}
        for problem in check.get("problems") or []:
            st.markdown(plain_text(f"Self check ({problem['rule']}): {problem['issue']}"))
        for p in prices:
            if p.get("filters"):
                st.markdown(f"**What the Price Agent Understood** ({p.get('approach')})")
                st.json(p["filters"])
        if turn.get("agent_errors"):
            st.error(turn["agent_errors"])
        cost = turn.get("cost_usd")
        st.caption(f"Retries: {turn.get('attempts', 0)}. "
                   + (f"Cost of this turn: about US${cost:.4f}." if cost is not None else ""))


# ---------- the page ----------

st.set_page_config(page_title="HomeWise Chat", page_icon="🏠", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)

if not HAS_LLM_KEY:
    st.error("Add OPENAI_API_KEY or LLM_API_KEY to .env; the chat makes live model calls.")
    st.stop()

app, connection = chat_graph()
if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = uuid.uuid4().hex

with st.sidebar:
    if st.button("New Chat", type="primary", width="stretch"):
        st.session_state["thread_id"] = uuid.uuid4().hex
        st.rerun()
    st.header("Chats")
    chats = saved_chats(app, connection)
    if not chats:
        st.caption("No saved chats yet.")
    for thread_id, title in chats:
        current = thread_id == st.session_state["thread_id"]
        if st.button(short(title), key=f"chat_{thread_id}", width="stretch",
                     type="secondary", disabled=current, help=title):
            st.session_state["thread_id"] = thread_id
            st.rerun()
    st.caption("Your chats are saved on this computer.")

logo_svg = LOGO_FILE.read_text(encoding="utf-8") if LOGO_FILE.exists() else ""
st.markdown(f'<div class="ag-header">{logo_svg}<div>'
            '<div class="ag-title"><span class="ag-home">Home</span><span class="ag-wise">Wise</span></div>'
            "<p>Ask about HDB resale prices or CPF housing rules, then keep asking.</p></div></div>"
            f'<div class="ag-road">{ROAD_SVG}</div>', unsafe_allow_html=True)

thread_id = st.session_state["thread_id"]
for turn in chat_history(app, thread_id):
    with st.chat_message("user"):
        st.markdown(plain_text(turn["user_question"]))
    with st.chat_message("assistant"):
        show_answer(turn)
        show_details(turn)

question = st.chat_input("Ask a question, or a follow-up")
if question and question.strip():
    with st.chat_message("user"):
        st.markdown(plain_text(question.strip()))
    with st.chat_message("assistant"):
        with st.spinner("Finding the answer..."):
            try:
                ask(app, thread_id, question.strip())
            except Exception as error:  # shown on the page instead of crashing the demo
                st.error(f"The answer could not be produced: {type(error).__name__}: {error}")
                st.stop()
    st.rerun()  # redraw from the saved history, and add the chat to the sidebar

st.markdown('<div class="ag-footer">General information only, not financial advice. '
            "Check the official HDB and CPF pages before you decide.</div>",
            unsafe_allow_html=True)
