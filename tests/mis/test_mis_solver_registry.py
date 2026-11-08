"""Tests for public MWIS solver selection through the built-in registry."""

import pytest

from qreduce.mis import (
    LocalGreedyMISBackend,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
)
from qreduce.solvers import BuiltinMISSolverId


def test_builtin_registry_resolves_local_greedy_solver() -> None:
    """The public solver ID maps to QReduce's dependency-free implementation."""

    registry = builtin_mis_solver_registry()

    assert registry.solver_ids == (BuiltinMISSolverId.LOCAL_GREEDY.value,)
    assert isinstance(registry.create(BuiltinMISSolverId.LOCAL_GREEDY.value), LocalGreedyMISBackend)


def test_unknown_mis_solver_is_rejected_without_substitution() -> None:
    """An unsupported solver ID never falls back to the built-in greedy solver."""

    with pytest.raises(UnknownMISSolverError, match="unknown_mis_solver"):
        builtin_mis_solver_registry().create("unknown_mis_solver")