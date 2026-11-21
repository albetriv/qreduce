"""Regression tests for UTF-8 text in the portfolio configurator DOM."""

from html.parser import HTMLParser
from pathlib import Path


class TextDOM(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []

    def handle_data(self, data):
        self.text.append(data)


def test_portfolio_dom_preserves_accents_and_math_symbols():
    page = Path(__file__).resolve().parents[1] / "uix" / "experiment_portfolio_mv.html"
    dom = TextDOM()
    dom.feed(page.read_bytes().decode("utf-8", errors="strict"))
    text = " ".join(dom.text)

    for expected in ("01 · Esperimento", "Identità e portfolio sintetico", "δᵢ", "λ", "Σ", "μ", "cardinalità"):
        assert expected in text
    for corrupted in ("Ã", "Â·", "Î´", "�"):
        assert corrupted not in text
