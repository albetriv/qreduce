"""Registry mapping public classical solver IDs to QReduce implementations."""

from collections.abc import Callable

from qreduce.classical.contracts import ClassicalBackend
from qreduce.classical.cplex_backend import CplexClassicalBackend
from qreduce.solvers import BuiltinClassicalSolverId


class UnknownClassicalSolverError(ValueError):
    """Raised when a requested classical solver is not registered."""


class ClassicalSolverRegistry:
    """Explicit classical-solver registry without automatic solver substitution."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], ClassicalBackend]] = {}

    def register(self, solver_id: str, factory: Callable[[], ClassicalBackend]) -> None:
        if not solver_id.strip():
            raise ValueError("solver_id cannot be blank.")
        if solver_id in self._factories:
            raise ValueError(f"Classical solver '{solver_id}' is already registered.")
        self._factories[solver_id] = factory

    def create(self, solver_id: str) -> ClassicalBackend:
        try:
            return self._factories[solver_id]()
        except KeyError as error:
            raise UnknownClassicalSolverError(f"Unknown classical solver: {solver_id}.") from error

    @property
    def solver_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def builtin_classical_solver_registry() -> ClassicalSolverRegistry:
    """Return the registry of classical solver integrations bundled by QReduce."""

    registry = ClassicalSolverRegistry()
    registry.register(BuiltinClassicalSolverId.CPLEX.value, CplexClassicalBackend)
    return registry