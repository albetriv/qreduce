"""Classical-backend integration boundaries for QReduce."""

from .capabilities import ClassicalRuntimeCapabilities
from .contracts import ClassicalBackend, ClassicalSolveRequest, ClassicalSolveResult
from .cplex_backend import CplexClassicalBackend
from .cplex_capability import (
    CplexRuntimeCapability,
    cplex_classical_capabilities,
    probe_cplex_runtime,
)
from .registry import (
    ClassicalSolverRegistry,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)

__all__ = [
    "ClassicalBackend",
    "ClassicalRuntimeCapabilities",
    "ClassicalSolveRequest",
    "ClassicalSolveResult",
    "ClassicalSolverRegistry",
    "CplexClassicalBackend",
    "CplexRuntimeCapability",
    "UnknownClassicalSolverError",
    "builtin_classical_solver_registry",
    "cplex_classical_capabilities",
    "probe_cplex_runtime",
]