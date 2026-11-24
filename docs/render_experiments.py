"""Render the experiment guides as standalone static HTML pages."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

import mistune

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "docs" / "experiments"
OUTPUT = SOURCES
GUIDES = (
    "portfolio", "portfolio-sr", "facility-location", "asset-liability-management",
    "riassicurazione-passiva", "cessione-crediti-deteriorati", "pianificazione-audit-interni",
)


def _inline_math(inline, match, state):
    state.append_token({"type": "tex_inline", "raw": match.group("tex_inline_body")})
    return match.end()


def _block_math(block, match, state):
    state.append_token({"type": "tex_block", "raw": match.group("tex_block_body")})
    return match.end()


def _math_plugin(md):
    # Code spans and fenced blocks take precedence over TeX delimiters.
    md.inline.register("tex_inline", r"\\\((?P<tex_inline_body>.+?)\\\)", _inline_math, before="escape")
    md.block.register("tex_block", r"^ {0,3}\\\[(?P<tex_block_body>[\s\S]*?)\\\][ \t]*(?:\n|$)", _block_math, before="paragraph")
    md.renderer.register("tex_inline", lambda renderer, text: r"\(" + html.escape(text) + r"\)")
    md.renderer.register("tex_block", lambda renderer, text: '<div class="math">\\[' + html.escape(text) + '\\]</div>\n')


def render(markdown: str) -> str:
    """Convert Markdown to a complete HTML page, retaining TeX for MathJax."""
    title_match = re.search(r"^# (.+)$", markdown, re.MULTILINE)
    if not title_match:
        raise ValueError("Missing document title")
    title = html.escape(title_match.group(1))
    parser = mistune.create_markdown(escape=True, plugins=["table", "strikethrough", _math_plugin])
    body = parser(markdown)
    return f'''<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body {{ font: 1rem/1.55 system-ui, sans-serif; max-width: 72rem; margin: 2rem auto; padding: 0 1rem; }} pre {{ overflow-x: auto; }} table {{ border-collapse: collapse; display: block; overflow-x: auto; }} th, td {{ border: 1px solid #aaa; padding: .4rem; }} .math {{ overflow-x: auto; }}</style>
<script>window.MathJax = {{tex: {{inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']]}}}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"></script>
</head>
<body>
<main>
{body}</main>
</body>
</html>
'''


def main() -> int:
    """Generate pages, or check that committed pages are up to date."""
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true", help="check generated pages without writing")
    args = cli.parse_args()
    pages = {name: render((SOURCES / f"{name}.md").read_text(encoding="utf-8")) for name in GUIDES}
    if args.check:
        stale = [name for name, page in pages.items() if not (OUTPUT / f"{name}.html").is_file() or (OUTPUT / f"{name}.html").read_text(encoding="utf-8") != page]
        if stale:
            print("Missing or outdated HTML: " + ", ".join(stale))
            return 1
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name, page in pages.items():
            (OUTPUT / f"{name}.html").write_text(page, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
