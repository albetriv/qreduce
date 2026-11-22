"""DOM regressions for contextual solver notices on all experiment pages."""

import json
import re
import shlex
import tomllib
from pathlib import Path

import pytest
from test_uix_js_execution import TestSolverInfoPanelDOMTransitions as _Transitions

PAGES = ("portfolio", "portfolio_sr", "facility_location")


def run_steps(page, steps):
    result = _Transitions().run_transition_test(page, steps)
    failures = [step for step in result["steps"] if any(
        not item["match"] for item in step["verify"]
    )]
    assert result["success"], json.dumps(failures or result, indent=2)
    return result


@pytest.mark.parametrize("page", PAGES)
def test_actual_solver_notices_and_baseline(page):
    rounds = "rounds" if page == "facility_location" else "maxRounds"
    classical = "solver" if page == "facility_location" else "classicalSolver"
    steps = [
        {"set": {rounds: "1", "misSolver": "local_greedy", classical: "scip"},
         "verify": {
             "misSolverInfoPanel": {"visible": True, "includes": ["Local Greedy", "senza SDK opzionali"],
                                    "excludes": ["Ocean", "Pulser", "minorminer"]},
             "classicalSolverInfoPanel": {"visible": True, "includes": ["SCIP", "PySCIPOpt"], "excludes": "CPLEX"},
             "embeddingWarningPanel": {"exists": False},
             "misBaselineNotice": {"count": 0},
         }},
        {"set": {"misSolver": "dwave_simulated_annealing", classical: "cplex"},
         "verify": {
             "misSolverInfoPanel": {"visible": True, "includes": ["Ocean", "dwave-samplers"],
                                    "excludes": ["Local Greedy", "Pulser"]},
             "classicalSolverInfoPanel": {"visible": True, "includes": ["CPLEX", "licenza"], "excludes": "PySCIPOpt"},
             "embeddingWarningPanel": {"exists": False},
         }},
    ]
    if page != "facility_location":
        steps.append({"set": {"misSolver": "pasqal_local"}, "verify": {
            "misSolverInfoPanel": {"visible": True,
                                   "includes": ["Pulser/QuTiP", "12 nodi", "poetry install --with experiments"],
                                   "excludes": ["Ocean", "--with pasqal"]},
            "embeddingWarningPanel": {"exists": False},
        }})
    steps.extend([
        {"set": {rounds: "0"}, "verify": {
            "misParamsCard": {"visible": False},
            "misBaselineNotice": {"count": 1, "visible": True, "includes": "backend MIS non viene utilizzato"},
            "misSolverInfoPanel": {"exists": False},
            "embeddingWarningPanel": {"exists": False},
            "misSolverInfoContainer": {"excludes": ["Ocean", "Pulser", "Local Greedy", "minorminer"]},
            "classicalSolverInfoPanel": {"visible": True, "includes": "CPLEX"},
        }},
        {"set": {rounds: "1", "misSolver": "local_greedy", classical: "scip"}, "verify": {
            "misParamsCard": {"visible": True},
            "misBaselineNotice": {"count": 0},
            "misSolverInfoPanel": {"visible": True, "includes": "Local Greedy"},
            "classicalSolverInfoPanel": {"includes": "SCIP", "excludes": "CPLEX"},
        }},
    ])
    run_steps(page, steps)


@pytest.mark.parametrize("page", PAGES)
def test_panel_nodes_survive_unrelated_changes(page):
    rounds = "rounds" if page == "facility_location" else "maxRounds"
    classical = "solver" if page == "facility_location" else "classicalSolver"
    run_steps(page, [
        {"set": {rounds: "1", "misSolver": "dwave_simulated_annealing", classical: "scip"},
         "remember": ["misSolverInfoPanel", "classicalSolverInfoPanel"]},
        {"set": {"runId": "unrelated_change", rounds: "2"}, "verify": {
            "misSolverInfoPanel": {"sameNode": True},
            "classicalSolverInfoPanel": {"sameNode": True},
        }},
        {"set": {classical: "cplex"}, "verify": {"misSolverInfoPanel": {"sameNode": True}},
         "remember": ["classicalSolverInfoPanel"]},
        {"set": {"misSolver": "local_greedy"},
         "verify": {"classicalSolverInfoPanel": {"sameNode": True}}},
        {"set": {rounds: "0"}, "remember": ["misBaselineNotice"]},
        {"set": {"runId": "baseline_unrelated", "misSolver": "dwave_simulated_annealing"},
         "verify": {"misBaselineNotice": {"sameNode": True, "count": 1}}},
    ])


@pytest.mark.parametrize("page", PAGES)
def test_solver_panels_follow_reset_and_favorite_restore(page):
    rounds = "rounds" if page == "facility_location" else "maxRounds"
    classical = "solver" if page == "facility_location" else "classicalSolver"
    backend = "dwave_simulated_annealing" if page == "facility_location" else "pasqal_local"
    fields = {rounds: "1", "misSolver": backend, classical: "cplex",
              "favoriteName": "solver context"}
    if page != "facility_location":
        fields.update({"pasqalShots": "321",
                       "maxRuntime" if page == "portfolio_sr" else "endToEndBudget": "0"})
    steps = [
        {"set": fields, "action": "saveFavorite"},
        {"action": "reset", "verify": {
            "classicalSolverInfoPanel": {"includes": "SCIP", "excludes": "CPLEX"},
        }},
        {"set": {"favoritesList": "solver context"}, "action": "loadFavorite",
         "verify": {
             "misParamsCard": {"visible": True},
             "misSolverInfoPanel": {"includes": "Ocean" if page == "facility_location" else "Pulser/QuTiP"},
             "classicalSolverInfoPanel": {"includes": "CPLEX", "excludes": "PySCIPOpt"},
             "misBaselineNotice": {"count": 0},
         }},
    ]
    result = run_steps(page, steps)
    assert f"--mis-solver{'-id' if page != 'facility_location' else ''} {backend}" in result["steps"][-1]["command"]



@pytest.mark.parametrize("page", ("portfolio", "portfolio_sr"))
def test_embedding_warnings_and_backend_values_are_retained(page):
    reads = "misNumReads" if page == "portfolio_sr" else "numReads"
    sweeps = "misNumSweeps" if page == "portfolio_sr" else "numSweeps"
    none = "" if page == "portfolio_sr" else "none"
    active = {"embeddingProfile": {"value": "pegasus_p16", "disabled": False},
              reads: {"value": "123", "disabled": False},
              sweeps: {"value": "456", "disabled": False}}
    inactive = {key: {**value, "disabled": True} for key, value in active.items()}
    result = run_steps(page, [
        {"set": {"maxRounds": "1", "misSolver": "dwave_simulated_annealing",
                 "embeddingProfile": "pegasus_p16", reads: "123", sweeps: "456"},
         "verify": {**active, "embeddingWarningPanel": {
             "count": 1, "visible": True, "includes": ["minorminer", "dwave-system", "dwave-graphs", "hardware reale"]}},
         "remember": ["embeddingWarningPanel", "misSolverInfoPanel"]},
        {"set": {"runId": "keep_warning"}, "verify": {
            "embeddingWarningPanel": {"sameNode": True}, "misSolverInfoPanel": {"sameNode": True}}},
        {"set": {"embeddingProfile": none}, "verify": {"embeddingWarningPanel": {"exists": False}}},
        {"set": {"embeddingProfile": "pegasus_p16", "misSolver": "pasqal_local", "pasqalShots": "321"},
         "verify": {**inactive, "embeddingWarningPanel": {"exists": False}}},
        {"set": {"misSolver": "local_greedy"}, "verify": {
            **inactive, "pasqalShots": {"value": "321", "disabled": True},
            "embeddingWarningPanel": {"exists": False}}},
        {"set": {"misSolver": "dwave_simulated_annealing", "maxRounds": "0"}, "verify": {
            **inactive, "embeddingWarningPanel": {"exists": False}}},
        {"set": {"maxRounds": "1"}, "verify": {
            **active, "embeddingWarningPanel": {"visible": True, "count": 1}}},
        {"set": {"misSolver": "pasqal_local"}, "verify": {
            "pasqalShots": {"value": "321", "disabled": False},
            "embeddingWarningPanel": {"exists": False}}},
    ])
    assert "--mis-embedding-profile" not in result["steps"][5]["command"]
    assert "--mis-embedding-profile pegasus_p16" in result["steps"][6]["command"]


@pytest.mark.parametrize("page", ("portfolio", "portfolio_sr"))
def test_pasqal_budget_error_is_accessible_at_budget_field(page):
    budget = "maxRuntime" if page == "portfolio_sr" else "endToEndBudget"
    in_budget_field = f"css:.field:has(#{budget}) #pasqalBudgetError"
    invalid = {"attributes": {"aria-invalid": "true"}}
    # aria-describedby may also name a help paragraph or a tooltip.
    described = f'css:#{budget}[aria-describedby~="pasqalBudgetError"]'
    result = run_steps(page, [
        {"set": {"runId": "budget_accessibility", "maxRounds": "1",
                 "misSolver": "pasqal_local", budget: "60"}, "verify": {
            "pasqalBudgetError": {"count": 1, "visible": True, "includes": "0"},
            in_budget_field: {"count": 1, "visible": True},
            described: {"count": 1}, budget: invalid,
        }},
        {"set": {budget: "0"}, "verify": {
            "pasqalBudgetError": {"visible": False},
            f'css:#{budget}[aria-invalid="true"]': {"count": 0},
        }},
        {"set": {budget: "60"}, "verify": {"pasqalBudgetError": {"visible": True}, budget: invalid}},
        {"set": {"misSolver": "local_greedy"}, "verify": {
            "pasqalBudgetError": {"visible": False},
            f'css:#{budget}[aria-invalid="true"]': {"count": 0},
        }},
        {"set": {"misSolver": "pasqal_local", "maxRounds": "0"}, "verify": {
            "pasqalBudgetError": {"visible": False},
            f'css:#{budget}[aria-invalid="true"]': {"count": 0},
        }},
        {"set": {"maxRounds": "1"}, "verify": {"pasqalBudgetError": {"visible": True}, budget: invalid}},
    ])
    assert result["steps"][0]["copyDisabled"] is True
    assert result["steps"][1]["copyDisabled"] is False



@pytest.mark.parametrize("page", PAGES)
def test_experiment_pulser_installation_instructions(page):
    filename = {"portfolio": "experiment_portfolio_mv.html",
                "portfolio_sr": "experiment_portfolio_sr.html",
                "facility_location": "experiment_facility_location.html"}[page]
    uix = Path(__file__).resolve().parents[1] / "uix"
    sources = [uix / filename, uix / "assets" / "solver_info.js"]
    if page != "portfolio_sr":
        sources.append(uix / "assets" / ("portfolio_mv.js" if page == "portfolio" else "facility_location.js"))
    for source in sources:
        instructions = re.findall(r"poetry install[^<\n\"']*", source.read_text())
        for instruction in instructions:
            if "pasqal" in instruction.lower() or "pulser" in instruction.lower():
                pytest.fail(f"{source}: obsolete installation instruction: {instruction}")


def test_pulser_dependency_belongs_to_experiments():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    assert "pulser-simulation (==1.10.1)" in config["dependency-groups"]["experiments"]
    assert "pasqal" not in config["dependency-groups"]
    locked = tomllib.loads((root / "poetry.lock").read_text())
    pulser = next(p for p in locked["package"] if p["name"] == "pulser-simulation")
    assert "experiments" in pulser["groups"]
    assert "pasqal" not in pulser["groups"]


@pytest.mark.parametrize("page", ("portfolio", "portfolio_sr"))
def test_contextual_commands_pass_full_cli_validation(page):
    if page == "portfolio":
        from qreduce.experiments.portfolio_mv.__main__ import (
            _build_parser,
            _validate_args,
        )
    else:
        from qreduce.experiments.portfolio_sr.__main__ import (
            _build_parser,
            _validate_args,
        )
    budget = "endToEndBudget" if page == "portfolio" else "maxRuntime"
    result = run_steps(page, [
        {"set": {"maxRounds": "1", "misSolver": "pasqal_local", budget: "0", "pasqalShots": "123"}},
        {"set": {"misSolver": "dwave_simulated_annealing"}},
        {"set": {"maxRounds": "0"}},
    ])
    for step in result["steps"]:
        tokens = shlex.split(step["command"])
        parser = _build_parser()
        args = parser.parse_args(tokens[tokens.index("-m") + 2:])
        _validate_args(parser, args)
