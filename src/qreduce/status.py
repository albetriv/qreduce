"""Normalized statuses and reasons shared by QReduce pipeline contracts."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Terminal outcome of a complete QReduce run."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class PipelineStage(StrEnum):
    """Pipeline stage at which a result or failure was observed."""

    VALIDATION = "validation"
    GRAPH = "graph"
    MIS = "mis"
    CANDIDATE_DOMAIN = "candidate_domain"
    RESTRICTION = "restriction"
    CLASSICAL = "classical"
    POSTCHECK = "postcheck"
    ARTIFACTS = "artifacts"


class TerminalReason(StrEnum):
    """Normalized terminal reasons required by the normative specification."""

    INVALID_CONFIGURATION = "invalid_configuration"
    ADAPTER_FAILURE = "adapter_failure"
    GRAPH_CONSTRUCTION_FAILED = "graph_construction_failed"
    MIS_BACKEND_UNAVAILABLE = "mis_backend_unavailable"
    MIS_PROVIDER_UNAVAILABLE = "mis_provider_unavailable"
    MIS_BACKEND_CAPABILITY_MISMATCH = "mis_backend_capability_mismatch"
    MIS_PROBLEM_REPRESENTATION_UNSUPPORTED = (
        "mis_problem_representation_unsupported"
    )
    MIS_SDK_DEPENDENCY_UNAVAILABLE = "mis_sdk_dependency_unavailable"
    MIS_CREDENTIALS_UNAVAILABLE = "mis_credentials_unavailable"
    MIS_COMPILATION_FAILED = "mis_compilation_failed"
    MIS_EMBEDDING_FAILED = "mis_embedding_failed"
    MIS_TRANSPILATION_FAILED = "mis_transpilation_failed"
    MIS_DEVICE_MAPPING_FAILED = "mis_device_mapping_failed"
    MIS_REMOTE_SUBMISSION_FAILED = "mis_remote_submission_failed"
    MIS_EXECUTION_FAILED = "mis_execution_failed"
    MIS_RESULT_NORMALIZATION_FAILED = "mis_result_normalization_failed"
    MIS_EXECUTION_TIME_BUDGET_EXHAUSTED = "mis_execution_time_budget_exhausted"
    NO_VALID_MIS_CANDIDATE = "no_valid_mis_candidate"
    CANDIDATE_DOMAIN_TOO_SMALL = "candidate_domain_too_small"
    CANDIDATE_DOMAIN_NO_MEANINGFUL_REDUCTION = (
        "candidate_domain_no_meaningful_reduction"
    )
    PROTECTED_ITEMS_EXCEED_CANDIDATE_DOMAIN_CAP = (
        "protected_items_exceed_candidate_domain_cap"
    )
    REDUCTION_ROUND_LIMIT_REACHED = "reduction_round_limit_reached"
    END_TO_END_TIME_BUDGET_EXHAUSTED = "end_to_end_time_budget_exhausted"
    CLASSICAL_BACKEND_UNAVAILABLE = "classical_backend_unavailable"
    CLASSICAL_SOLVER_FAILED = "classical_solver_failed"
    CLASSICAL_SOLVER_INFEASIBLE = "classical_solver_infeasible"
    CLASSICAL_SOLVER_TIME_LIMITED = "classical_solver_time_limited"
    POSTCHECK_FAILED = "postcheck_failed"
    ARTIFACT_WRITE_FAILED = "artifact_write_failed"
    UNSUPPORTED_PROBLEM_STRUCTURE = "unsupported_problem_structure"


class ClassicalSolverStatus(StrEnum):
    """Status reported by the residual classical solver."""

    NOT_RUN = "not_run"
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    TIME_LIMIT_WITH_FEASIBLE_INCUMBENT = "time_limit_with_feasible_incumbent"
    TIME_LIMIT_WITHOUT_FEASIBLE_INCUMBENT = "time_limit_without_feasible_incumbent"
    INFEASIBLE = "infeasible"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class PostcheckStatus(StrEnum):
    """Outcome of domain-adapter post-checking."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class AdoptionStatus(StrEnum):
    """Whether a final solution may be adopted by the caller."""

    ADOPTED = "adopted"
    NOT_ADOPTED = "not_adopted"
    UNAVAILABLE = "unavailable"


class FallbackPolicy(StrEnum):
    """Fallback behavior supported by the initial single-pass milestone."""

    FAIL = "fail"


class ExecutionMode(StrEnum):
    """Requested MIS execution location."""

    LOCAL = "local"
    REMOTE = "remote"


class BackendFamily(StrEnum):
    """Provider-neutral MIS backend family."""

    CLASSICAL_EXACT = "classical_exact"
    CLASSICAL_HEURISTIC = "classical_heuristic"
    ANNEALING = "annealing"
    GATE_BASED = "gate_based"
    NEUTRAL_ATOM = "neutral_atom"
    HYBRID = "hybrid"


class ProblemForm(StrEnum):
    """Canonical problem representation accepted by a MIS backend."""

    MIS_GRAPH = "mis_graph"
    QUBO = "qubo"
    BQM = "bqm"
    ISING = "ising"


class PostcheckMode(StrEnum):
    """Tolerance regime used by a domain adapter post-check."""

    STRICT = "strict"
    SOLVER_TOLERANCE_ALIGNED = "solver_tolerance_aligned"


class PolicySelectionStatus(StrEnum):
    """Caller-supplied provenance classification, preserved without reinterpretation."""

    USER_SUPPLIED = "user_supplied"
    EXTERNALLY_CALIBRATED = "externally_calibrated"
    EXTERNALLY_VALIDATED = "externally_validated"
    EXPERIMENTAL = "experimental"
    UNKNOWN = "unknown"


class UnsupportedBackendParameterPolicy(StrEnum):
    """Handling of provider-specific parameters absent from backend capability."""

    REJECT = "reject"