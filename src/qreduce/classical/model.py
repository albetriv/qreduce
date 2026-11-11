"""Solver-agnostic mathematical representation of residual MILP and MIQP models."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable


class ClassicalVariableType(StrEnum):
    """Variable domains supported by the bundled classical integrations."""

    BINARY = "binary"
    CONTINUOUS = "continuous"
    INTEGER = "integer"


class LinearConstraintSense(StrEnum):
    """Supported linear-constraint relations."""

    EQUAL = "equal"
    LESS_EQUAL = "less_equal"
    GREATER_EQUAL = "greater_equal"


@dataclass(frozen=True, slots=True)
class ClassicalVariable:
    """One named decision variable in a solver-independent residual model."""

    name: str
    variable_type: ClassicalVariableType
    lower_bound: float | None = None
    upper_bound: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Variable names cannot be blank.")
        for field_name, value in (("lower_bound", self.lower_bound), ("upper_bound", self.upper_bound)):
            if value is not None and (not math.isfinite(value) or isinstance(value, bool)):
                raise ValueError(f"{field_name} must be finite when supplied.")
        if self.lower_bound is not None and self.upper_bound is not None and self.lower_bound > self.upper_bound:
            raise ValueError("lower_bound cannot exceed upper_bound.")


@dataclass(frozen=True, slots=True)
class LinearConstraint:
    """A named linear constraint with a finite right-hand side."""

    name: str
    coefficients: Mapping[str, float]
    sense: LinearConstraintSense
    right_hand_side: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Constraint names cannot be blank.")
        coefficients = dict(self.coefficients)
        if not coefficients or any(not name.strip() or not math.isfinite(value) for name, value in coefficients.items()):
            raise ValueError("Constraint coefficients must be non-empty with non-blank names and finite values.")
        if not math.isfinite(self.right_hand_side):
            raise ValueError("Constraint right_hand_side must be finite.")
        object.__setattr__(self, "coefficients", MappingProxyType(coefficients))


@dataclass(frozen=True, slots=True)
class QuadraticObjectiveTerm:
    """One expanded polynomial term: coefficient * left_variable * right_variable.

    The coefficient is the actual coefficient in the objective polynomial, not
    an entry of a solver-specific quadratic matrix.
    """

    left_variable: str
    right_variable: str
    coefficient: float

    def __post_init__(self) -> None:
        if not self.left_variable.strip() or not self.right_variable.strip():
            raise ValueError("Quadratic objective variables cannot be blank.")
        if isinstance(self.coefficient, bool) or not math.isfinite(self.coefficient):
            raise ValueError("Quadratic objective coefficients must be finite.")


@dataclass(frozen=True, slots=True)
class ClassicalOptimizationModel:
    """Canonical minimization model compiled by a domain adapter, not a solver backend."""

    variables: tuple[ClassicalVariable, ...]
    linear_objective: Mapping[str, float] = field(default_factory=dict)
    quadratic_objective: tuple[QuadraticObjectiveTerm, ...] = ()
    linear_constraints: tuple[LinearConstraint, ...] = ()

    def __post_init__(self) -> None:
        variables = tuple(self.variables)
        variable_names = tuple(variable.name for variable in variables)
        if not variables or len(set(variable_names)) != len(variable_names):
            raise ValueError("Model variables must be non-empty and have unique names.")
        known_names = set(variable_names)
        linear_objective = dict(self.linear_objective)
        if any(not name.strip() or name not in known_names or not math.isfinite(value) for name, value in linear_objective.items()):
            raise ValueError("Linear objective must use model variable names and finite coefficients.")
        quadratic_objective = tuple(self.quadratic_objective)
        if any(term.left_variable not in known_names or term.right_variable not in known_names for term in quadratic_objective):
            raise ValueError("Quadratic objective terms must use model variable names.")
        constraints = tuple(self.linear_constraints)
        if len({constraint.name for constraint in constraints}) != len(constraints):
            raise ValueError("Linear constraint names must be unique.")
        if any(set(constraint.coefficients) - known_names for constraint in constraints):
            raise ValueError("Linear constraints must use model variable names.")
        object.__setattr__(self, "variables", variables)
        object.__setattr__(self, "linear_objective", MappingProxyType(linear_objective))
        object.__setattr__(self, "quadratic_objective", quadratic_objective)
        object.__setattr__(self, "linear_constraints", constraints)

    @property
    def variable_names(self) -> tuple[str, ...]:
        return tuple(variable.name for variable in self.variables)


@runtime_checkable
class ClassicalModelProvider(Protocol):
    """Domain boundary that compiles one opaque residual problem into a generic model."""

    def build_classical_model(self) -> ClassicalOptimizationModel: ...