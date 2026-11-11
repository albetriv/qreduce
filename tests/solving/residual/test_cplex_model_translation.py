"""Tests for translating solver-neutral quadratic models into the CPLEX API."""

from types import SimpleNamespace

from qreduce.solving.residual import (
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
    QuadraticObjectiveTerm,
)
from qreduce.solving.residual.cplex_backend import _build_cplex_model


class FakeCplex:
    """Minimal CPLEX-shaped object that records calls from the model translator."""

    infinity = 1.0e20

    class SparsePair:
        def __init__(self, *, ind: list[str], val: list[float]) -> None:
            self.ind = ind
            self.val = val

    def __init__(self) -> None:
        self.objective = SimpleNamespace(
            sense=SimpleNamespace(minimize="minimize"),
            set_sense=lambda value: setattr(self, "objective_sense", value),
            set_linear=lambda value: setattr(self, "linear_objective", value),
            set_quadratic_coefficients=lambda value: setattr(
                self, "quadratic_objective", value
            ),
        )
        self.variables = SimpleNamespace(
            type=SimpleNamespace(binary="B", continuous="C", integer="I"),
            add=lambda **kwargs: setattr(self, "added_variables", kwargs),
        )
        self.linear_constraints = SimpleNamespace(
            add=lambda **kwargs: setattr(self, "added_constraints", kwargs),
        )


def test_cplex_translation_converts_expanded_diagonal_polynomial_terms() -> None:
    """CPLEX receives its half-quadratic diagonal convention, not the generic one."""

    generic_model = ClassicalOptimizationModel(
        variables=(
            ClassicalVariable("delta", ClassicalVariableType.BINARY, 0.0, 1.0),
            ClassicalVariable("x", ClassicalVariableType.CONTINUOUS, 0.0, None),
            ClassicalVariable("y", ClassicalVariableType.CONTINUOUS, 0.0, None),
        ),
        linear_objective={"x": -0.1},
        quadratic_objective=(
            QuadraticObjectiveTerm("x", "x", 0.4),
            QuadraticObjectiveTerm("x", "y", 0.6),
        ),
        linear_constraints=(
            LinearConstraint(
                "link",
                {"x": 1.0, "delta": -0.7},
                LinearConstraintSense.LESS_EQUAL,
                0.0,
            ),
        ),
    )

    model = _build_cplex_model(SimpleNamespace(Cplex=FakeCplex, SparsePair=FakeCplex.SparsePair, infinity=FakeCplex.infinity), generic_model)

    assert model.added_variables["types"] == ["B", "C", "C"]
    assert model.added_variables["ub"] == [1.0, FakeCplex.infinity, FakeCplex.infinity]
    assert model.quadratic_objective == [("x", "x", 0.8), ("x", "y", 0.6)]
    assert model.added_constraints["senses"] == ["L"]