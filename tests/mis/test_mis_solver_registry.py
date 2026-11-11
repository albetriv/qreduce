"""Tests for built-in and application-extended MWIS solver registries."""

import pytest

from qreduce.mis import (
    MISSolverRegistry,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
)
from qreduce.mis.dwave_simulated_annealing_backend import (
    DWaveSimulatedAnnealingMISBackend,
)
from qreduce.mis.local_backend import LocalGreedyMISBackend


class CallerMISBackend:
    """Minimal caller-owned factory product for registry resolution tests."""


def test_builtin_registry_resolves_bundled_mis_solvers() -> None:
    """The standard catalog supplies QReduce's local heuristic and Ocean simulator."""

    registry = builtin_mis_solver_registry()

    assert registry.solver_ids == ("dwave_simulated_annealing", "local_greedy")
    assert isinstance(registry.create("local_greedy"), LocalGreedyMISBackend)
    assert isinstance(
        registry.create("dwave_simulated_annealing"), DWaveSimulatedAnnealingMISBackend
    )


def test_registry_resolves_a_solver_registered_by_the_caller() -> None:
    """Applications can deliberately extend an otherwise empty registry."""

    registry = MISSolverRegistry(include_builtins=False)
    registry.register("caller_mis", CallerMISBackend)

    assert registry.solver_ids == ("caller_mis",)
    assert isinstance(registry.create("caller_mis"), CallerMISBackend)


def test_unknown_mis_solver_is_rejected_without_substitution() -> None:
    """An unsupported solver ID never falls back to another registered solver."""

    with pytest.raises(UnknownMISSolverError, match="unknown_mis_solver"):
        builtin_mis_solver_registry().create("unknown_mis_solver")