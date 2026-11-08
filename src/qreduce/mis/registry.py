"""Registry mapping public MWIS solver IDs to QReduce implementations."""

from collections.abc import Callable

from qreduce.mis.compilation import MISExecutionAdapter
from qreduce.mis.local_backend import LocalGreedyMISBackend
from qreduce.solvers import BuiltinMISSolverId


class UnknownMISSolverError(ValueError):
    """Raised when a requested MWIS solver is not registered."""


class MISSolverRegistry:
    """Small explicit registry; external registration can be added without API changes."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], MISExecutionAdapter]] = {}

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
    """Return a registry with dependency-free solvers bundled by QReduce."""

    registry = MISSolverRegistry()
    registry.register(BuiltinMISSolverId.LOCAL_GREEDY.value, LocalGreedyMISBackend)
    return registry