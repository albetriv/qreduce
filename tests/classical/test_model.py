"""Tests for the solver-agnostic residual optimization model contract."""

import pytest

from qreduce.classical import (
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
    QuadraticObjectiveTerm,
)


def test_model_freezes_and_validates_a_generic_miqp() -> None:
    """A domain adapter can expose a reusable solver-neutral MIQP model."""

    model = ClassicalOptimizationModel(
        variables=(
            ClassicalVariable("delta", ClassicalVariableType.BINARY, 0.0, 1.0),
            ClassicalVariable("x", ClassicalVariableType.CONTINUOUS, 0.0, None),
        ),
        linear_objective={"x": -0.1},
        quadratic_objective=(QuadraticObjectiveTerm("x", "x", 0.4),),
        linear_constraints=(
            LinearConstraint(
                "link",
                {"x": 1.0, "delta": -0.7},
                LinearConstraintSense.LESS_EQUAL,
                0.0,
            ),
        ),
    )

    assert model.variable_names == ("delta", "x")
    assert model.linear_objective["x"] == -0.1
    assert model.quadratic_objective[0].coefficient == 0.4
    assert model.linear_constraints[0].coefficients["delta"] == -0.7


def test_model_rejects_unknown_variables_in_constraints() -> None:
    """Backend translators never receive a model with dangling variable names."""

    with pytest.raises(ValueError, match="model variable names"):
        ClassicalOptimizationModel(
            variables=(ClassicalVariable("x", ClassicalVariableType.CONTINUOUS),),
            linear_constraints=(
                LinearConstraint(
                    "invalid",
                    {"unknown": 1.0},
                    LinearConstraintSense.EQUAL,
                    0.0,
                ),
            ),
        )