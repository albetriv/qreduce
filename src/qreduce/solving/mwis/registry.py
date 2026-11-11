"""Factory registry for QReduce-provided and application-provided MWIS solvers."""

from collections.abc import Callable

from qreduce.solving.mwis.compilation import MISExecutionAdapter


class UnknownMISSolverError(ValueError):
    """Raised when a requested MWIS solver is not registered."""


class MISSolverRegistry:
    """Resolve bundled solver IDs and allow explicit application extensions."""

    def __init__(self, *, include_builtins: bool = True) -> None:
        self._factories: dict[str, Callable[[], MISExecutionAdapter]] = (
            _builtin_factories() if include_builtins else {}
        )

    def register(self, solver_id: str, factory: Callable[[], MISExecutionAdapter]) -> None:
        if not solver_id.strip():
            raise ValueError("solver_id cannot be blank.")
        if solver_id in self._factories:
            raise ValueError(f"MIS solver '{solver_id}' is already registered.")
        self._factories[solver_id] = factory

    def create(self, solver_id: str) -> MISExecutionAdapter:
        try:
            return self._factories[solver_id]()
        except KeyError as error:
            raise UnknownMISSolverError(f"Unknown MIS solver: {solver_id}.") from error

    @property
    def solver_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def builtin_mis_solver_registry() -> MISSolverRegistry:
    """Create the standard QReduce MWIS solver catalog."""

    return MISSolverRegistry()


def _builtin_factories() -> dict[str, Callable[[], MISExecutionAdapter]]:
    """Import local implementations only while constructing the built-in catalog."""

    from qreduce.solvers import BuiltinMISSolverId
    from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
        DWaveSimulatedAnnealingMISBackend,
    )
    from qreduce.solving.mwis.local_backend import LocalGreedyMISBackend

    return {
        BuiltinMISSolverId.LOCAL_GREEDY: LocalGreedyMISBackend,
        BuiltinMISSolverId.DWAVE_SIMULATED_ANNEALING: DWaveSimulatedAnnealingMISBackend,
    }