"""Domain-adapter contracts kept independent from solver runtimes."""

from qreduce.domains.contracts import (
    DomainEvaluationMetric,
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    LogicalVariableCounts,
    ProtectionDeclaration,
    ReducibleProblemAdapter,
)

__all__ = [
    "DomainEvaluationMetric",
    "DomainValidationResult",
    "FinalSolutionValidationResult",
    "FixingEntry",
    "FixingManifest",
    "LogicalVariableCounts",
    "ProtectionDeclaration",
    "ReducibleProblemAdapter",
]