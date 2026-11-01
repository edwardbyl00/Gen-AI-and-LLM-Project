"""Tests for the demo interface, run headless in demo mode (no API key needed)."""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[1] / "ui" / "app.py")


def demo_app():
    """Select saved samples explicitly, even if a developer has a local key."""
    app = st_testing.AppTest.from_file(APP, default_timeout=30).run()
    return app.radio[0].set_value("Demo Mode (Saved Samples)").run()


def run_example(index):
    """Open the page and click one example question (it is asked straight away)."""
    app = demo_app()
    app.button(key=f"example_{index}").click().run()
    return app


def all_markdown(app):
    return "\n".join(m.value for m in app.markdown)


def test_page_loads_in_demo_mode():
    app = demo_app()
    assert not app.exception
    text = all_markdown(app)
    assert 'class="ag-home">Home</span><span class="ag-wise">Wise' in text
    assert "How It Works" in text            # start screen explains the system


def test_demo_price_answer_shows_answer_price_facts_and_steps():
    app = run_example(0)
    assert not app.exception
    text = all_markdown(app)
    assert "Answered from 902 past resale deals" in text
    # Dollar signs are written as &#36;, so Streamlit shows prices instead of a maths formula.
    assert "<b>&#36;665,000</b>" in text and "$665" not in text
    assert "<b>902</b>" in text                # key facts in bold
    assert "4-room flats in Tampines sold for a median of" in text   # one-line headline
    assert "Read the full answer" in text
    assert "4-Room Flats in Tampines" in text
    assert "Lowest Deal" in text and "Oct 2025 to Sep 2026" in text
    assert "How This Answer Was Made" in text and "Checked resale deals" in text
    assert "How It Works" not in text        # start screen gone once there is an answer
    assert any(e.label.startswith("Behind the Scenes") for e in app.expander)


def test_demo_unknown_place_shows_no_price_figures():
    app = run_example(2)
    assert not app.exception
    text = all_markdown(app)
    assert "Median Price" not in text        # no invented figures
    assert "not one of the HDB towns" in text
    assert "Not fully answered" in text


def test_demo_mode_explains_missing_sample():
    app = run_example(3)                     # the CPF question has no saved sample
    assert not app.exception
    assert any("only has answers" in w.value for w in app.warning)


def test_typed_question_uses_the_form():
    app = demo_app()
    app.text_input(key="question").input("What did 4-room flats in Tampines sell for recently?")
    app.button[0].click().run()              # the form's Ask button
    assert not app.exception
    assert "Price Facts" in all_markdown(app)


def load_page_helpers():
    """Load ui/app.py with a stand-in for Streamlit, to test its HTML helpers directly."""
    import importlib.util
    import sys
    from unittest import mock
    fake = mock.MagicMock()
    fake.session_state = {}
    fake.radio.side_effect = lambda label, options, **k: options[2] if label == "System" else options[0]
    fake.text_input.return_value = ""
    fake.form_submit_button.return_value = False
    fake.columns.side_effect = lambda spec, **k: [mock.MagicMock()
                                                 for _ in range(spec if isinstance(spec, int) else len(spec))]
    spec = importlib.util.spec_from_file_location("homewise_page", APP)
    page = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"streamlit": fake}):
        spec.loader.exec_module(page)
    return page


def test_clarification_and_cannot_answer_are_shown():
    """The team's 'Need more detail' status and 'Can't answer' list appear in the HomeWise design."""
    page = load_page_helpers()
    bundle = {"answer": {"answer": "Which town do you mean?", "declined": False,
                         "needs_clarification": True,
                         "cannot_answer": [{"part": "Next year's price", "reason": "no forecasts"}]},
              "price_result": None, "steps": []}
    out = page.answer_card_html(bundle)
    assert "Need more detail" in out
    assert "Can&#39;t answer" in out and "no forecasts" in out


def test_headline_covers_both_parts_of_a_both_question():
    """'Can I use my CPF ... and how much would it cost?' must not lose the CPF answer."""
    page = load_page_helpers()
    price = {"town": "CLEMENTI", "flat_type": "3 ROOM", "period_start": "2025-10",
             "period_end": "2026-09", "median_price": 434000, "n_deals": 206}
    bundle = {"routing": {"route": "both"}, "price_result": price,
              "answer": {"declined": False, "answer": "Yes. You can use CPF Ordinary Account savings "
                         "to buy an HDB resale flat, including a 3-room resale flat.[4][6] More text."}}
    line = page.headline(bundle)
    assert line.startswith("Yes, you can use CPF Ordinary Account savings to buy an HDB resale flat.")
    assert "3-room flats in Clementi sold for a median of $434,000" in line
    assert "[4]" not in line
    bundle["routing"]["route"] = "price"
    assert page.headline(bundle).startswith("3-room flats in Clementi")
