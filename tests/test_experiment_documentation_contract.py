"""Editorial and CLI documentation contract; no solver execution required."""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ROOT / "docs" / "experiments"
EXECUTABLE = {
    "portfolio": "qreduce.experiments.portfolio_mv",
    "portfolio-sr": "qreduce.experiments.portfolio_sr",
    "facility-location": "qreduce.experiments.facility_location.run",
}
PROPOSALS = (
    "asset-liability-management", "cessione-crediti-deteriorati",
    "pianificazione-audit-interni", "riassicurazione-passiva",
)
NAMES = (*EXECUTABLE, *PROPOSALS)
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


@pytest.mark.parametrize(("name", "url"), [
    ("portfolio", "https://arxiv.org/abs/2607.01037"),
    ("portfolio-sr", "https://arxiv.org/abs/2302.12291"),
])
def test_required_paper_reference_in_source(name, url):
    assert url in section(source(name), 7)


def source(name):
    return (GUIDES / f"{name}.md").read_text(encoding="utf-8")


def section(text, number):
    match = re.search(rf"(?ms)^## {number}\. [^\n]+\n(.*?)(?=^## |\Z)", text)
    assert match, f"missing section {number}"
    return match.group(1)


@pytest.mark.parametrize("name", NAMES)
def test_section_structure_and_formulation(name):
    text = source(name)
    assert len(re.findall(r"(?m)^# .+", text)) == 1
    headings = re.findall(r"(?m)^## (.+)$", text)
    expected = ["1. Descrizione del problema", "2. Formulazione matematica",
                "3. CLI unificata", "4. Parametri", "5. Directory degli artifact"]
    assert headings[:len(expected)] == expected
    assert headings[len(expected):] in (["6. Riferimenti"], ["6. Note specifiche", "7. Riferimenti"])
    math = section(text, 2)
    assert r"\[" in math and r"\]" in math
    assert not re.search(r"(?m)^```", math)
    subsections = re.findall(r"(?m)^### (\d+)\.(\d+)\b", text)
    assert all(int(major) == 4 and int(minor) == i
               for i, (major, minor) in enumerate(subsections, 1))


@pytest.mark.parametrize("name", NAMES)
def test_cli_and_artifact_contract(name):
    text = source(name)
    cli = section(text, 3).strip()
    artifacts = section(text, 5)
    if name in EXECUTABLE:
        assert cli == f"```bash\npoetry run python -m {EXECUTABLE[name]} --help\n```"
        assert text.count("```") == 2
        assert "--output-root" in artifacts
        root = {"portfolio": "portfolio_mv", "portfolio-sr": "portfolio_sr",
                "facility-location": "facility_location"}[name]
        assert f"outputs/{root}" in artifacts
    else:
        assert cli == "Non disponibile: l’esperimento non è ancora eseguibile."
        assert "Non applicabile: l’esperimento non produce ancora artifact." in artifacts
        assert not FLAG.search(text)
        assert "```" not in text
        assert re.search(r"non (?:è |sono )?ancora eseguibil", section(text, 1), re.IGNORECASE)


@pytest.mark.parametrize("name,module", EXECUTABLE.items())
def test_documented_options_match_executed_help(name, module):
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"], cwd=ROOT,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    help_flags = set(FLAG.findall(result.stdout))
    # Table names, not prose mentions: the latter cannot hide omissions.
    names = re.findall(r"(?m)^\|\s*([^|]+)\|", section(source(name), 4))
    documented = set(FLAG.findall("\n".join(names)))
    assert help_flags == documented, (
        f"{name}: missing from guide: {sorted(help_flags - documented)}; "
        f"not in help: {sorted(documented - help_flags)}"
    )
    if name == "facility-location":
        assert re.search(r"(?m)^\s*instance\s", result.stdout)
        assert "`instance`" in "\n".join(names)


@pytest.mark.parametrize("name", NAMES)
def test_pragmatic_editorial_exclusions(name):
    text = source(name)
    # Solver names are legitimate parameter descriptions, not installation advice.
    forbidden = [r"\bUIX\b", r"\bconfigurator[ei]\b", r"\.ipynb\b",
                 r"\bpip install\b", r"\bpoetry install\b", r"\bpython -m\b"]
    without_cli = text.replace(section(text, 3), "")
    for pattern in forbidden:
        assert not re.search(pattern, without_cli, re.IGNORECASE), (name, pattern)
    assert not re.search(r"(?m)^\s*[├└│]", section(text, 5))


@pytest.mark.parametrize("name", NAMES)
def test_local_markdown_links_and_anchors(name):
    text = source(name)
    for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
        url = urlsplit(target)
        if url.scheme or url.netloc or target.startswith("//"):
            continue
        path = (GUIDES / unquote(url.path)).resolve() if url.path else GUIDES / f"{name}.md"
        assert path.is_file(), f"{name}: missing {target}"
        if url.fragment and path.suffix == ".md":
            headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", path.read_text(encoding="utf-8"))
            slugs = [re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings]
            assert unquote(url.fragment) in slugs, f"{name}: missing anchor {target}"
