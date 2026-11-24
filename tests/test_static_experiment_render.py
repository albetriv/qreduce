"""Technical tests for the standalone experiment documentation renderer."""

import html
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("mistune")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_experiments", ROOT / "docs/render_experiments.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def test_tex_and_markdown_survive_without_javascript():
    source = r"""# Titolo

Testo \(x_1 < y_2\) e [link](https://example.org).

\[
\sum_i x_i & <= y_2
\]

| Nome | Valore |
| --- | --- |
| A | B |

`\(non_math\)`

```text
\[not_math\]
```
"""
    page = renderer.render(source)
    assert r"\(x_1 &lt; y_2\)" in page
    assert "\\[\n\\sum_i x_i &amp; &lt;= y_2\n\\]" in page
    assert "<table>" in page and '<a href="https://example.org">link</a>' in page
    assert r"<code>\(non_math\)</code>" in page
    assert r"\[not_math\]" in page
    assert "mathjax@3.2.2" in page and "window.MathJax" in page
    assert r"inlineMath: [['\\(', '\\)']]" in page
    assert r"displayMath: [['\\[', '\\]']]" in page
    assert "fetch(" not in page
    assert html.unescape(r"\(x_1 &lt; y_2\)") in html.unescape(page)
    assert renderer.render(source) == page


def test_versioned_pages_are_in_sync():
    pages = [renderer.OUTPUT / f"{name}.html" for name in renderer.GUIDES]
    for name, page in zip(renderer.GUIDES, pages, strict=True):
        assert page.is_file(), page
        assert page.read_text(encoding="utf-8") == renderer.render(
            (renderer.SOURCES / f"{name}.md").read_text(encoding="utf-8")
        ), page


def test_missing_title_is_rejected():
    with pytest.raises(ValueError, match="title"):
        renderer.render("Testo senza titolo")


def test_check_detects_missing_and_stale_pages(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(renderer, "SOURCES", tmp_path)
    monkeypatch.setattr(renderer, "OUTPUT", tmp_path / "out")
    monkeypatch.setattr(renderer, "GUIDES", ("guide",))
    (tmp_path / "guide.md").write_text("# Titolo\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["render", "--check"])
    assert renderer.main() == 1
    monkeypatch.setattr(sys, "argv", ["render"])
    assert renderer.main() == 0
    monkeypatch.setattr(sys, "argv", ["render", "--check"])
    assert renderer.main() == 0
    (tmp_path / "guide.md").write_text("# Nuovo titolo\n", encoding="utf-8")
    assert renderer.main() == 1
