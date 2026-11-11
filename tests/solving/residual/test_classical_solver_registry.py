"""Tests for built-in and application-extended classical solver registries."""

import pytest

from qreduce.solving.residual import (
    ClassicalSolverRegistry,
    CplexClassicalBackend,
    ScipClassicalBackend,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)


class CallerClassicalBackend:
    """Minimal caller-owned factory product for registry resolution tests."""


def test_builtin_registry_resolves_known_solver_ids() -> None:
    """The standard catalog is supplied by QReduce without caller registration."""

    registry = builtin_classical_solver_registry()

    assert registry.solver_ids == ("cplex", "scip")
    assert isinstance(registry.create("cplex"), CplexClassicalBackend)
    assert isinstance(registry.create("scip"), ScipClassicalBackend)


def test_registry_resolves_a_solver_registered_by_the_caller() -> None:
    """Applications can deliberately extend an otherwise empty registry."""

    registry = ClassicalSolverRegistry(include_builtins=False)
    registry.register("caller_classical", CallerClassicalBackend)

    assert registry.solver_ids == ("caller_classical",)
    assert isinstance(registry.create("caller_classical"), CallerClassicalBackend)


def test_unknown_classical_solver_is_rejected_without_substitution() -> None:
    """An unsupported solver ID never falls back to another registered solver."""

    with pytest.raises(UnknownClassicalSolverError, match="unknown_classical_solver"):
        builtin_classical_solver_registry().create("unknown_classical_solver")