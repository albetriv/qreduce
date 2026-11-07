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
from qreduce.mis.local_backend import LocalGreedyMISBackend
from qreduce.mis.normalization import (
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)

__all__ = [
    "BackendReportedScoreKind",
    "CompiledMISJob",
    "DeduplicationResult",
    "LocalGreedyMISBackend",
    "MISBackendRequest",
    "MISBackendResult",
    "MISCompilationRequest",
    "MISCompilationResult",
    "MISCompletionStatus",
    "MISExecutionAdapter",
    "MISNormalizationResult",
    "RawMISSample",
    "deduplicate_raw_mis_samples",
    "normalize_backend_result",
    "validate_compilation_request",
]