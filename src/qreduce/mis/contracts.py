"""Immutable provider-neutral contracts for MIS compilation and execution."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.capabilities import RuntimeCapabilities
from qreduce.mwis.graph import CanonicalMWISProblem, Edge
from qreduce.mwis.validation import MWISValidationError, normalize_binary_vector
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


class MISCompletionStatus(StrEnum):
    """Completion state for an individual compilation or execution operation."""

    COMPLETED = "completed"
    TIME_LIMITED = "time_limited"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BackendReportedScoreKind(StrEnum):
    """Declared semantics of a score supplied by a backend or provider."""

    QUBO_ENERGY = "qubo_energy"
    ISING_ENERGY = "ising_energy"
    HAMILTONIAN_EXPECTATION = "hamiltonian_expectation"
    PROBABILITY = "probability"
    OBJECTIVE_ESTIMATE = "objective_estimate"
    PROVIDER_SPECIFIC = "provider_specific"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MISCompilationRequest:
    """Explicit, serializable request to compile a canonical MIS problem."""

    run_id: str
    round_index: int
    node_order: tuple[str, ...]
    residual_time_budget_seconds: float
    requested_provider_id: str
    requested_backend_id: str
    requested_backend_family: BackendFamily
    requested_execution_mode: ExecutionMode
    required_problem_form: ProblemForm
    requested_device_id: str | None = None
    compilation_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonnegative_int(self.round_index, "round_index")
        _require_node_order(self.node_order, "node_order")
        _require_positive_finite(self.residual_time_budget_seconds, "residual_time_budget_seconds")
        _require_nonempty(self.requested_provider_id, "requested_provider_id")
        _require_nonempty(self.requested_backend_id, "requested_backend_id")
        object.__setattr__(self, "node_order", tuple(self.node_order))
        object.__setattr__(self, "compilation_parameters", MappingProxyType(dict(self.compilation_parameters)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class CompiledMISJob:
    """Provider-neutral successful compilation artifact ready for execution."""

    compiled_job_id: str
    run_id: str
    round_index: int
    node_order: tuple[str, ...]
    problem_form: ProblemForm
    compiled_problem: CanonicalMWISProblem
    requested_provider_id: str
    requested_backend_id: str
    effective_provider_id: str
    effective_backend_id: str
    backend_family: BackendFamily
    execution_mode: ExecutionMode
    effective_device_id: str | None
    runtime_seconds: float
    effective_compilation_parameters: Mapping[str, object]
    capabilities_snapshot: RuntimeCapabilities

    def __post_init__(self) -> None:
        _require_nonempty(self.compiled_job_id, "compiled_job_id")
        _require_nonempty(self.run_id, "run_id")
        _require_nonnegative_int(self.round_index, "round_index")
        _require_node_order(self.node_order, "node_order")
        _require_nonnegative_finite(self.runtime_seconds, "runtime_seconds")
        if tuple(self.node_order) != self.compiled_problem.graph.node_ids:
            raise MWISValidationError("node_order_mismatch", "node_order", "Job order must match compiled problem.")
        object.__setattr__(self, "node_order", tuple(self.node_order))
        object.__setattr__(
            self,
            "effective_compilation_parameters",
            MappingProxyType(dict(self.effective_compilation_parameters)),
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MISCompilationResult:
    """Observable compilation outcome, including explicit failures."""

    compiled_job: CompiledMISJob | None
    requested_provider_id: str
    requested_backend_id: str
    effective_provider_id: str | None
    effective_backend_id: str | None
    runtime_seconds: float
    completion_status: MISCompletionStatus
    effective_compilation_parameters: Mapping[str, object] = field(default_factory=dict)
    terminal_reason: TerminalReason | None = None
    diagnostic_message: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_finite(self.runtime_seconds, "runtime_seconds")
        _validate_completion(self.completion_status, self.terminal_reason, self.compiled_job is not None)
        object.__setattr__(
            self,
            "effective_compilation_parameters",
            MappingProxyType(dict(self.effective_compilation_parameters)),
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MISBackendRequest:
    """Explicit, serializable request to execute a compiled MIS job."""

    run_id: str
    round_index: int
    compiled_job_id: str
    node_order: tuple[str, ...]
    random_seed: int | None
    requested_solution_count: int
    residual_time_budget_seconds: float
    execution_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.compiled_job_id, "compiled_job_id")
        _require_nonnegative_int(self.round_index, "round_index")
        _require_node_order(self.node_order, "node_order")
        _require_positive_int(self.requested_solution_count, "requested_solution_count")
        _require_positive_finite(self.residual_time_budget_seconds, "residual_time_budget_seconds")
        object.__setattr__(self, "node_order", tuple(self.node_order))
        object.__setattr__(self, "execution_parameters", MappingProxyType(dict(self.execution_parameters)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RawMISSample:
    """One backend sample, without any implicit optimality or feasibility claim."""

    raw_sample_id: str
    node_order: tuple[str, ...]
    delta: tuple[int, ...]
    occurrence_count: int = 1
    backend_reported_score: float | None = None
    backend_reported_score_kind: BackendReportedScoreKind = BackendReportedScoreKind.UNAVAILABLE
    canonical_qubo_energy: float | None = None
    canonical_ising_energy: float | None = None
    selection_weight: float | None = None
    num_selected: int | None = None
    is_independent_set: bool | None = None
    violated_edges: tuple[Edge, ...] = ()
    num_violated_edges: int | None = None
    source_provider_id: str = ""
    source_backend_id: str = ""
    execution_runtime_seconds: float | None = None
    effective_compilation_parameters: Mapping[str, object] = field(default_factory=dict)
    effective_execution_parameters: Mapping[str, object] = field(default_factory=dict)
    raw_backend_metadata: Mapping[str, object] = field(default_factory=dict)
    source_raw_sample_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.raw_sample_id, "raw_sample_id")
        _require_node_order(self.node_order, "node_order")
        normalized_delta = normalize_binary_vector(self.delta)
        if len(normalized_delta) != len(self.node_order):
            raise MWISValidationError("selection_length_mismatch", "delta", "delta length must equal node_order.")
        _require_positive_int(self.occurrence_count, "occurrence_count")
        if self.execution_runtime_seconds is not None:
            _require_nonnegative_finite(self.execution_runtime_seconds, "execution_runtime_seconds")
        object.__setattr__(self, "node_order", tuple(self.node_order))
        object.__setattr__(self, "delta", normalized_delta)
        object.__setattr__(self, "violated_edges", tuple(self.violated_edges))
        object.__setattr__(self, "effective_compilation_parameters", MappingProxyType(dict(self.effective_compilation_parameters)))
        object.__setattr__(self, "effective_execution_parameters", MappingProxyType(dict(self.effective_execution_parameters)))
        object.__setattr__(self, "raw_backend_metadata", MappingProxyType(redact_metadata(dict(self.raw_backend_metadata))))
        source_ids = self.source_raw_sample_ids or (self.raw_sample_id,)
        object.__setattr__(self, "source_raw_sample_ids", tuple(source_ids))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MISBackendResult:
    """Observable MIS execution outcome, including partial and failed runs."""

    samples: tuple[RawMISSample, ...]
    requested_provider_id: str
    requested_backend_id: str
    effective_provider_id: str | None
    effective_backend_id: str | None
    backend_family: BackendFamily
    execution_mode: ExecutionMode
    capabilities_snapshot: RuntimeCapabilities
    runtime_seconds: float
    effective_execution_parameters: Mapping[str, object] = field(default_factory=dict)
    completion_status: MISCompletionStatus = MISCompletionStatus.COMPLETED
    terminal_reason: TerminalReason | None = None
    diagnostic_message: str | None = None
    effective_device_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_finite(self.runtime_seconds, "runtime_seconds")
        _validate_completion(self.completion_status, self.terminal_reason, True)
        object.__setattr__(self, "samples", tuple(self.samples))
        object.__setattr__(self, "effective_execution_parameters", MappingProxyType(dict(self.effective_execution_parameters)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MISNormalizationResult:
    """Result of recomputing canonical sample metrics without repair or ranking."""

    samples: tuple[RawMISSample, ...]
    terminal_reason: TerminalReason | None = None
    diagnostic_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Deterministic grouping of samples by their canonical delta vector."""

    samples: tuple[RawMISSample, ...]
    discarded_samples: tuple[RawMISSample, ...]

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def _validate_completion(
    completion_status: MISCompletionStatus,
    terminal_reason: TerminalReason | None,
    has_compiled_job: bool,
) -> None:
    if completion_status is MISCompletionStatus.COMPLETED and terminal_reason is not None:
        raise ValueError("A completed MIS operation cannot have a terminal reason.")
    if completion_status is MISCompletionStatus.FAILED and terminal_reason is None:
        raise ValueError("A failed MIS operation requires a terminal reason.")
    if completion_status is MISCompletionStatus.COMPLETED and not has_compiled_job:
        raise ValueError("Completed compilation requires a compiled job.")


def _require_nonempty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MWISValidationError("blank_value", field, "Value must be a non-blank string.")


def _require_node_order(node_order: tuple[str, ...], field: str) -> None:
    if not isinstance(node_order, tuple | list) or any(not isinstance(node_id, str) or not node_id for node_id in node_order):
        raise MWISValidationError("invalid_node_order", field, "node_order must contain non-blank string IDs.")
    if len(set(node_order)) != len(node_order):
        raise MWISValidationError("duplicate_node_id", field, "node_order must be unique.")


def _require_nonnegative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MWISValidationError("invalid_integer", field, "Value must be an integer >= 0.")


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MWISValidationError("invalid_integer", field, "Value must be an integer > 0.")


def _require_positive_finite(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise MWISValidationError("invalid_numeric_value", field, "Value must be finite and > 0.")


def _require_nonnegative_finite(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise MWISValidationError("invalid_numeric_value", field, "Value must be finite and >= 0.")