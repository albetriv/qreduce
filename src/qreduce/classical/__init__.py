"""Classical-backend integration boundaries for QReduce."""

from .contracts import ClassicalBackend, ClassicalSolveRequest, ClassicalSolveResult
from .cplex_backend import CplexClassicalBackend
from .cplex_capability import CplexRuntimeCapability, probe_cplex_runtime

__all__ = [
    "ClassicalBackend",
    "ClassicalSolveRequest",
    "ClassicalSolveResult",
    "CplexClassicalBackend",
    "CplexRuntimeCapability",
    "probe_cplex_runtime",
]