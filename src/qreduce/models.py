"""Immutable, provider-neutral domain contracts for QReduce runs."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from qreduce.status import (
    AdoptionStatus,
    ClassicalSolverStatus,
    PipelineStage,
    PolicySelectionStatus,
    PostcheckMode,
    PostcheckStatus,
    RunStatus,
    TerminalReason,
)


@dataclass(frozen=True, slots=True)
class ReductionPolicy:
    """Resolved controls for the reduction portion of a run."""

    max_reduction_rounds: int
    candidate_domain_min_items: int
    candidate_domain_max_items: int
    num_source_mis_candidates: int
    min_reduction_ratio: float
    target_binary_variables: int
    max_end_to_end_runtime_seconds: float


@dataclass(frozen=True, slots=True)
class LambdaEdgePolicy:
    """Serializable provenance for the selected MWIS edge-penalty policy."""

    policy_id: str
    policy_version: str
    effective_lambda_edge: float | None
    formula_description: str | None = None
    weight_normalization: str | None = None
    noncertifying_behavior: str | None = None
    proof_condition_satisfied: bool | None = None


@dataclass(frozen=True, slots=True)
class MISExecutionOptions:
    """Provider-neutral MIS execution options and declared conditional parameters."""

    requested_solution_count: int
    random_seed: int | None
    max_distinct_samples: int
    repair_enabled: bool
    repair_max_iterations: int
    minimum_candidate_jaccard_distance: float
    exact_solver_max_variables: int
    execution_time_limit_seconds: float | None = None
    compilation_time_limit_seconds: float | None = None
    provider_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze provider parameters so the resolved request cannot be mutated."""

        object.__setattr__(
            self,
            "provider_parameters",
            MappingProxyType(dict(self.provider_parameters)),
        )


@dataclass(frozen=True, slots=True)
class ClassicalSolveOptions:
    """Resolved controls for the residual classical solve and its post-check."""

    classical_solver_id: str
    time_limit_seconds: float
    mip_gap_tolerance: float | None
    threads: int | None
    model_export_enabled: bool
    primal_feasibility_tolerance: float
    integrality_tolerance: float
    objective_recomputation_absolute_tolerance: float
    objective_recomputation_relative_tolerance: float
    postcheck_mode: PostcheckMode
    random_seed: int | None = None
    model_export_path: str | None = None


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Immutable caller-supplied identity for one in-memory QReduce run."""

    run_id: str


@dataclass(frozen=True, slots=True)
class PolicyProvenance:
    """Opaque caller-provided policy provenance retained without reinterpretation."""

    policy_id: str | None = None
    policy_version: str | None = None
    policy_hash: str | None = None
    policy_source: str | None = None
    policy_selection_status: PolicySelectionStatus | None = None
    external_policy_selection_reference: str | None = None
    external_evaluation_reference: str | None = None
    declared_instance_class: str | None = None
    declared_validity_scope: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedRunConfig:
    """Complete immutable request, resolved before a QReduce run begins."""

    schema_version: str
    reduction: ReductionPolicy
    lambda_edge: float | None
    lambda_edge_policy: LambdaEdgePolicy | None
    allow_noncertifying_penalty: bool
    mis_solver_id: str
    mis_execution: MISExecutionOptions
    classical_solve: ClassicalSolveOptions
    run_identity: RunIdentity
    policy_provenance: PolicyProvenance = field(default_factory=PolicyProvenance)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic, serialization-ready representation."""

        from qreduce.artifacts.metadata import redact_metadata, to_primitive

        return redact_metadata(to_primitive(self))  # type: ignore[return-value]

    def to_canonical_json(self) -> str:
        """Return deterministic JSON suitable for persisted resolved configuration."""

        from qreduce.artifacts.metadata import canonical_json

        return canonical_json(self)

    def config_hash(self) -> str:
        """Return the SHA-256 digest of this resolved configuration."""

        from qreduce.artifacts.metadata import sha256_hex

        return sha256_hex(self)


@dataclass(frozen=True, slots=True)
class RoundResult:
    """Serializable partial result for one reduction round."""

    round_index: int
    stage: PipelineStage
    terminal_reason: TerminalReason | None = None
    runtime_seconds: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze metadata captured at the end of a reduction round."""

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, object]:
        """Return primitive metadata suitable for a future round artifact."""

        from qreduce.artifacts.metadata import to_primitive

        return to_primitive(self)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Terminal, serializable run outcome without adapter/runtime objects."""

    run_id: str
    run_status: RunStatus
    stage: PipelineStage
    terminal_reason: TerminalReason | None
    classical_solver_status: ClassicalSolverStatus
    postcheck_status: PostcheckStatus
    adoption_status: AdoptionStatus
    round_results: tuple[RoundResult, ...] = ()
    diagnostic_message: str | None = None
    config_hash: str | None = None
    input_hash: str | None = None
    policy_hash: str | None = None

    def __post_init__(self) -> None:
        """Reject terminal states that would make adoption ambiguous."""

        if self.run_status is RunStatus.SUCCESS:
            if self.adoption_status is not AdoptionStatus.ADOPTED:
                raise ValueError("A successful run must have an adopted solution.")
            if self.postcheck_status is not PostcheckStatus.PASSED:
                raise ValueError("A successful run must have a passed post-check.")
            if (
                self.classical_solver_status
                is ClassicalSolverStatus.TIME_LIMIT_WITH_FEASIBLE_INCUMBENT
            ):
                raise ValueError(
                    "A time-limited incumbent can only produce partial_success."
                )
        if self.run_status is RunStatus.FAILED and self.adoption_status is AdoptionStatus.ADOPTED:
            raise ValueError("A failed run cannot adopt a solution.")
        if (
            self.postcheck_status is PostcheckStatus.FAILED
            and self.adoption_status is AdoptionStatus.ADOPTED
        ):
            raise ValueError("A post-check failure cannot be adopted.")

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready terminal result."""

        from qreduce.artifacts.metadata import to_primitive

        return to_primitive(self)
