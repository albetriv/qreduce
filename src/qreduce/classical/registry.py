"""Factory registry for QReduce-provided and application-provided classical solvers."""

from collections.abc import Callable

from qreduce.classical.contracts import ClassicalBackend


class UnknownClassicalSolverError(ValueError):
    """Raised when a requested classical solver is not registered."""


class ClassicalSolverRegistry:
    """Resolve bundled solver IDs and allow explicit application extensions."""

    def __init__(self, *, include_builtins: bool = True) -> None:
        self._factories: dict[str, Callable[[], ClassicalBackend]] = (
            _builtin_factories() if include_builtins else {}
        )

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
    """Create the standard QReduce classical solver catalog."""

    return ClassicalSolverRegistry()


def _builtin_factories() -> dict[str, Callable[[], ClassicalBackend]]:
    """Keep optional bindings lazy by importing backend modules, not their SDKs."""

    from qreduce.classical.cplex_backend import CplexClassicalBackend
    from qreduce.classical.scip_backend import ScipClassicalBackend
    from qreduce.solvers import BuiltinClassicalSolverId

    return {
        BuiltinClassicalSolverId.CPLEX: CplexClassicalBackend,
        BuiltinClassicalSolverId.SCIP: ScipClassicalBackend,
    }