"""Tests for public classical solver selection through the built-in registry."""

import pytest

from qreduce.classical import (
    CplexClassicalBackend,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)
from qreduce.solvers import BuiltinClassicalSolverId


def test_builtin_registry_resolves_cplex_solver_without_importing_binding() -> None:
    """Creating the CPLEX adapter does not require importing the optional binding."""

    registry = builtin_classical_solver_registry()

    assert registry.solver_ids == (BuiltinClassicalSolverId.CPLEX.value,)
    assert isinstance(registry.create(BuiltinClassicalSolverId.CPLEX.value), CplexClassicalBackend)


def test_unknown_classical_solver_is_rejected_without_substitution() -> None:
    """An unsupported solver ID never falls back to CPLEX or any other solver."""

    with pytest.raises(UnknownClassicalSolverError, match="unknown_classical_solver"):
        builtin_classical_solver_registry().create("unknown_classical_solver")