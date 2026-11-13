"""Single-pass, multi-round, and unified orchestration for QReduce."""

from qreduce.pipeline.multi_round import (
    RecoveryAttempt,
    run_multi_round,
)
from qreduce.pipeline.single_pass import (
    CandidateDomainItemRecord,
    CandidateRecord,
    run_single_pass,
)
from qreduce.pipeline.unified import (
    PipelineRunResult,
    ReductionRoundResult,
    run_pipeline,
)

__all__ = [
    "CandidateDomainItemRecord",
    "CandidateRecord",
    "PipelineRunResult",
    "RecoveryAttempt",
    "ReductionRoundResult",
    "run_multi_round",
    "run_pipeline",
    "run_single_pass",
]