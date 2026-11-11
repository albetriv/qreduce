"""Classical-backend integration boundaries for QReduce."""

from .capabilities import ClassicalRuntimeCapabilities
from .contracts import ClassicalBackend, ClassicalSolveRequest, ClassicalSolveResult
from .cplex_backend import CplexClassicalBackend
from .model import (
    ClassicalModelProvider,
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
    QuadraticObjectiveTerm,
)
from .registry import (
    ClassicalSolverRegistry,
    UnknownClassicalSolverError,
    builtin_classical_solver_registry,
)
from .scip_backend import ScipClassicalBackend

__all__ = [
    "ClassicalBackend",
    "ClassicalModelProvider",
    "ClassicalOptimizationModel",
    "ClassicalRuntimeCapabilities",
    "ClassicalSolveRequest",
    "ClassicalSolveResult",
    "ClassicalSolverRegistry",
    "ClassicalVariable",
    "ClassicalVariableType",
    "CplexClassicalBackend",
    "LinearConstraint",
    "LinearConstraintSense",
    "QuadraticObjectiveTerm",
    "ScipClassicalBackend",
    "UnknownClassicalSolverError",
    "builtin_classical_solver_registry",
]