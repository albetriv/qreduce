"""Regression checks for the configurators' removed mathematics panel."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "page",
    [
        "experiment_facility_location.html",
        "experiment_portfolio_mv.html",
        "experiment_portfolio_sr.html",
    ],
)
def test_configurators_do_not_include_math_panel(page):
    html = (Path(__file__).resolve().parents[1] / "uix" / page).read_text(
        encoding="utf-8"
    )
    assert 'id="mathPanel"' not in html
    assert "math_formulation.js" not in html
    assert "Formulazione matematica" not in html