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
    assert "AskGov SG" in all_markdown(app)


def test_demo_price_answer_shows_answer_strip_and_steps():
    app = run_example(0)
    assert not app.exception
    text = all_markdown(app)
    assert "Answer" in [h.value for h in app.subheader]
    # Dollar signs are escaped, so Streamlit shows prices instead of a maths formula.
    assert "\\$665,000" in text
    # The price strip, with median, average and both ends.
    assert "Price Facts: 4-Room Flats in Tampines" in text
    assert "Median &#36;665,000" in text and "Lowest Deal" in text
    assert "Oct 2025 to Sep 2026" in text
    assert any(e.label == "How This Answer Was Made" for e in app.expander)
    # Main information first: the answer comes before the details and the examples.
    order = [h.value for h in app.subheader]
    assert order.index("Answer") < order.index("More Details")


def test_demo_unknown_place_shows_no_strip_figures():
    app = run_example(2)
    assert not app.exception
    text = all_markdown(app)
    assert "Median" not in text            # no invented figures
    assert "not one of the HDB towns" in text
    assert "Not fully answered" in text


def test_demo_mode_explains_missing_sample():
    app = run_example(3)                   # the CPF question has no saved sample
    assert not app.exception
    assert any("only has answers" in w.value for w in app.warning)


def test_typed_question_uses_the_form():
    app = demo_app()
    app.text_input(key="question").input("What did 4-room flats in Tampines sell for recently?")
    app.button[0].click().run()            # the form's Ask button
    assert not app.exception
    assert "Price Facts" in all_markdown(app)


def test_examples_move_below_the_answer():
    app = demo_app()
    assert "Or Try One of These" in all_markdown(app)
    app.button(key="example_0").click().run()
    text = all_markdown(app)
    assert "Try Another Question" in text
    assert text.index("Price Facts") < text.index("Try Another Question")
