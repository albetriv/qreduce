"""Provider-neutral execution of the canonical MWIS reduction problem."""

from qreduce.solving.mwis.compilation import (
    MISExecutionAdapter,
    validate_compilation_request,
)
from qreduce.solving.mwis.contracts import (
    BackendReportedScoreKind,
    CompiledMISJob,
    DeduplicationResult,
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
    MISCompletionStatus,
    MISNormalizationResult,
    RawMISSample,
)
from qreduce.solving.mwis.normalization import (
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.solving.mwis.registry import (
    MISSolverRegistry,
    UnknownMISSolverError,
    builtin_mis_solver_registry,
)

__all__ = [
    "BackendReportedScoreKind",
    "CompiledMISJob",
    "DeduplicationResult",
    "MISBackendRequest",
    "MISBackendResult",
    "MISCompilationRequest",
    "MISCompilationResult",
    "MISCompletionStatus",
    "MISExecutionAdapter",
    "MISNormalizationResult",
    "MISSolverRegistry",
    "RawMISSample",
    "UnknownMISSolverError",
    "builtin_mis_solver_registry",
    "deduplicate_raw_mis_samples",
    "normalize_backend_result",
    "validate_compilation_request",
]