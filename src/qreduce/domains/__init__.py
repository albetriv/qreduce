"""Domain-adapter contracts kept independent from solver runtimes."""

from qreduce.domains.contracts import (
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    ReducibleProblemAdapter,
)

__all__ = [
    "DomainValidationResult",
    "FinalSolutionValidationResult",
    "FixingEntry",
    "FixingManifest",
    "ReducibleProblemAdapter",
]