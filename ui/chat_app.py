"""HomeWise chat interface (P3; HomeWise look by P1).

A chat version of P1's demo page (ui/app.py), running P3's LangGraph graph
with memory. The chat itself (graph, memory and how each turn is drawn) lives in
ui/chat_view.py, which the main page's Chat button also uses.

Run from the project root:
    streamlit run ui/chat_app.py
"""

import uuid

import streamlit as st

from chat_view import (CSS, HAS_LLM_KEY, LOGO_FILE, ROAD_SVG, ask, chat_graph, chat_history,
                       plain_text, saved_chats, short, show_answer, show_details)


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
