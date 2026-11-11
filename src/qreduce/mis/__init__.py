"""Provider-neutral MIS compilation, execution and sample normalization contracts."""

from qreduce.mis.compilation import MISExecutionAdapter, validate_compilation_request
from qreduce.mis.contracts import (
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
from qreduce.mis.normalization import (
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.mis.registry import (
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