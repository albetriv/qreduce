from pathlib import Path

import pytest

from qreduce.experiments.facility_location.datasets import parse_or_library
from qreduce.experiments.facility_location.formulation import (
    FacilityLocationResidualProblem,
)
from qreduce.experiments.facility_location.postcheck import validate_solution


def test_parser_and_objective_use_full_demand_costs():
    problem = parse_or_library("2 1\n 4 3 6 5\n 10 7 11")
    model = FacilityLocationResidualProblem(problem).build_classical_model()
    assert problem.allocation_costs == ((7, 11),)
    assert model.linear_objective["x_0_0"] == 7
    assert model.linear_objective["x_1_0"] == 11
    assert model.linear_constraints[1].coefficients["x_0_0"] == 10


@pytest.mark.parametrize("text", ["1 1 2 0 1", "1 1 2 0 1 2 extra", "1 1 capacity 0 1 2", "1 1 2 0 nan 2"])
def test_invalid_input(text):
    with pytest.raises(ValueError):
        parse_or_library(text)


def test_fixing_covers_linked_variables():
    problem = parse_or_library("2 1 4 0 6 0 10 0 0")
    model = FacilityLocationResidualProblem(problem, (0,)).build_classical_model()
    assert {c.name for c in model.linear_constraints if c.name.startswith("fix_")} == {"fix_delta_0", "fix_x_0_0"}


def test_reference_requires_exact_bytes():
    from qreduce.experiments.facility_location.datasets import identify_reference
    path = Path(__file__).resolve().parents[3] / "data/benchmarks/or_library/capacitated_facility_location/cap41.txt"
    if not path.exists():
        pytest.skip("cap41 dataset not available locally")
    data = path.read_bytes()
    assert identify_reference(data)["instance_id"] == "cap41"
    assert identify_reference(data + b" ") is None


def test_postcheck_fractional_solution_and_violations():
    problem = parse_or_library("2 1 4 3 6 5 10 7 11")
    values = {"delta_0": 1, "delta_1": 1, "x_0_0": 0.4, "x_1_0": 0.6}
    result = validate_solution(problem, values, objective=17.4)
    assert result.feasible
    assert result.objective == pytest.approx(17.4)
    assert not validate_solution(problem, values, excluded=(0,)).feasible
    assert not validate_solution(problem, {**values, "x_0_0": 0.9}).feasible
    assert not validate_solution(problem, values, objective=20).feasible


@pytest.mark.integration
def test_cap41_scip_baseline():
    pytest.importorskip("pyscipopt")
    from qreduce.experiments.facility_location.datasets import load_or_library
    from qreduce.solving.residual.contracts import ClassicalSolveRequest
    from qreduce.solving.residual.scip_backend import ScipClassicalBackend

    path = Path(__file__).resolve().parents[3] / "data/benchmarks/or_library/capacitated_facility_location/cap41.txt"
    if not path.exists():
        pytest.skip("cap41 dataset not available locally")
    problem = load_or_library(path)
    request = ClassicalSolveRequest("cap41-test", 0, 60, 60, 60.0, None, 0, 1, False, requested_solver_id="scip")
    result = ScipClassicalBackend().solve(FacilityLocationResidualProblem(problem), request)
    assert result.is_optimal, result.diagnostic_message
    assert result.objective_value == pytest.approx(1040444.375, abs=0.01)
    assert validate_solution(problem, result.variable_values, objective=result.objective_value).feasible