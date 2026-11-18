"""Validation helpers for immutable resolved run configuration."""

import math
from dataclasses import dataclass

from qreduce.models import ResolvedRunConfig
from qreduce.status import TerminalReason

# Default timeout for classical solver invocations when not explicitly configured.
# Used by experiment interfaces (portfolio, facility_location, web) as the default
# value for classical_time_limit_seconds.
DEFAULT_CLASSICAL_TIME_LIMIT_SECONDS: float = 60.0

# Default budget for end-to-end pipeline execution when not explicitly configured.
DEFAULT_END_TO_END_BUDGET_SECONDS: float = 60.0


def validate_timeout_value(value: object, field_name: str) -> str | None:
    """Validate a timeout or budget value.

    Accepts finite floats >= 0. Rejects booleans, NaN, infinity, negative
    values, and non-numeric types. Returns None if valid, or an error message.

    Args:
        value: The value to validate.
        field_name: The name of the field for error messages.

    Returns:
        None if valid, or an error message string if invalid.
    """
    if isinstance(value, bool):
        return f"{field_name} must be a number, not a boolean"
    if not isinstance(value, (int, float)):
        return f"{field_name} must be a number, got {type(value).__name__}"
    if not math.isfinite(value):
        return f"{field_name} must be a finite number, not NaN or infinity"
    if value < 0:
        return f"{field_name} must be >= 0 (0 means unlimited)"
    return None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One observable validation violation without runtime-specific objects."""

    code: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Serializable outcome of pre-execution validation."""

    is_valid: bool
    terminal_reason: TerminalReason | None
    issues: tuple[ValidationIssue, ...] = ()

    @classmethod
    def valid(cls) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True, terminal_reason=None)

    @classmethod
    def invalid(
        cls,
        *issues: ValidationIssue,
        terminal_reason: TerminalReason = TerminalReason.INVALID_CONFIGURATION,
    ) -> "ValidationResult":
        """Create an invalid result with a normalized terminal reason."""
        return cls(is_valid=False, terminal_reason=terminal_reason, issues=issues)


@dataclass(frozen=True, slots=True)
class EffectiveTimeout:
    """Timeout determined from classical limit and residual budget.

    Represents the actual time limit to pass to a backend, distinguishing:
    - A finite limit (timeout_seconds > 0)
    - No configured limit (is_unlimited=True, timeout_seconds=None)
    - Budget exhausted (is_unlimited=False, timeout_seconds=None, validation invalid)

    The backend should:
    - Apply the limit if timeout_seconds is finite and positive
    - Run without a time limit if is_unlimited is True
    - Not run at all if validation is invalid (budget exhausted)
    """

    timeout_seconds: float | None
    validation: ValidationResult
    is_unlimited: bool = False


def validate_resolved_run_config(config: ResolvedRunConfig) -> ValidationResult:
    """Validate static invariants without inspecting a reduction graph."""
    issues: list[ValidationIssue] = []
    reduction = config.reduction
    execution = config.mis_execution
    classical = config.classical_solve

    if classical.model_export_enabled and (
        not isinstance(classical.model_export_path, str)
        or not classical.model_export_path.strip()
    ):
        _add_issue(
            issues, "missing_export_path", "classical_solve.model_export_path",
            "Model export requires an explicit non-blank file path.",
        )

    _require_nonempty(issues, "schema_version", config.schema_version)
    _require_nonempty(issues, "run_identity.run_id", config.run_identity.run_id)
    _require_nonempty(issues, "mis_solver_id", config.mis_solver_id)
    _require_nonempty(
        issues, "classical_solve.classical_solver_id", classical.classical_solver_id
    )

    _require_int_at_least(
        issues,
        "reduction.max_reduction_rounds",
        reduction.max_reduction_rounds,
        0,
    )
    # Recovery requires at least one reduction round
    if reduction.max_reduction_rounds == 0:
        if reduction.max_recovery_attempts != 0:
            _add_issue(
                issues,
                "recovery_requires_reduction",
                "reduction.max_recovery_attempts",
                "Recovery requires max_reduction_rounds >= 1.",
            )
        if reduction.recovery_policy_on_domain_too_small != "fail":
            _add_issue(
                issues,
                "recovery_requires_reduction",
                "reduction.recovery_policy_on_domain_too_small",
                "Recovery requires max_reduction_rounds >= 1.",
            )
        if reduction.recovery_policy_on_infeasible != "fail":
            _add_issue(
                issues,
                "recovery_requires_reduction",
                "reduction.recovery_policy_on_infeasible",
                "Recovery requires max_reduction_rounds >= 1.",
            )
    _require_int_at_least(
        issues,
        "reduction.candidate_domain_min_items",
        reduction.candidate_domain_min_items,
        0,
    )
    _require_int_at_least(
        issues,
        "reduction.candidate_domain_max_items",
        reduction.candidate_domain_max_items,
        0,
    )
    if reduction.candidate_domain_min_items > reduction.candidate_domain_max_items:
        _add_issue(
            issues,
            "candidate_domain_bounds_inverted",
            "reduction.candidate_domain_min_items",
            "candidate_domain_min_items cannot exceed candidate_domain_max_items.",
        )
    _require_int_at_least(
        issues,
        "reduction.num_source_mis_candidates",
        reduction.num_source_mis_candidates,
        1,
    )
    _require_int_at_least(
        issues,
        "reduction.target_binary_variables",
        reduction.target_binary_variables,
        0,
    )
    _require_finite_at_least(
        issues, "reduction.min_reduction_ratio", reduction.min_reduction_ratio, 0.0
    )
    if reduction.min_reduction_ratio > 1.0:
        _add_issue(
            issues,
            "ratio_above_one",
            "reduction.min_reduction_ratio",
            "min_reduction_ratio cannot exceed 1.",
        )
    _require_finite_nonnegative(
        issues,
        "reduction.max_end_to_end_runtime_seconds",
        reduction.max_end_to_end_runtime_seconds,
    )
    _validate_recovery_policy(
        issues,
        "reduction.recovery_policy_on_domain_too_small",
        reduction.recovery_policy_on_domain_too_small,
    )
    _validate_recovery_policy(
        issues,
        "reduction.recovery_policy_on_infeasible",
        reduction.recovery_policy_on_infeasible,
    )
    _require_int_at_least(
        issues,
        "reduction.max_recovery_attempts",
        reduction.max_recovery_attempts,
        0,
    )
    if reduction.max_recovery_attempts > 0 and (
        reduction.recovery_policy_on_domain_too_small == "fail"
        and reduction.recovery_policy_on_infeasible == "fail"
    ):
        _add_issue(
            issues,
            "recovery_attempts_without_policy",
            "reduction.max_recovery_attempts",
            "max_recovery_attempts > 0 requires at least one recovery policy other than fail.",
        )

    if config.lambda_edge is None and config.lambda_edge_policy is None:
        _add_issue(
            issues,
            "missing_lambda_edge",
            "lambda_edge",
            "A lambda_edge or lambda_edge_policy is required.",
        )
    if config.lambda_edge is not None:
        _require_finite_above_zero(issues, "lambda_edge", config.lambda_edge)
    if config.lambda_edge_policy is not None:
        _require_nonempty(
            issues, "lambda_edge_policy.policy_id", config.lambda_edge_policy.policy_id
        )
        _require_nonempty(
            issues,
            "lambda_edge_policy.policy_version",
            config.lambda_edge_policy.policy_version,
        )
        if config.lambda_edge_policy.effective_lambda_edge is not None:
            _require_finite_above_zero(
                issues,
                "lambda_edge_policy.effective_lambda_edge",
                config.lambda_edge_policy.effective_lambda_edge,
            )
        elif config.lambda_edge is None:
            _add_issue(
                issues,
                "missing_effective_lambda_edge",
                "lambda_edge_policy.effective_lambda_edge",
                "A lambda_edge_policy used without lambda_edge must declare effective_lambda_edge.",
            )
    if (
        config.lambda_edge is not None
        and config.lambda_edge_policy is not None
        and config.lambda_edge_policy.effective_lambda_edge is not None
        and config.lambda_edge != config.lambda_edge_policy.effective_lambda_edge
    ):
        _add_issue(
            issues,
            "lambda_edge_policy_mismatch",
            "lambda_edge_policy.effective_lambda_edge",
            "lambda_edge and lambda_edge_policy.effective_lambda_edge must match when both are provided.",
        )
    if config.allow_noncertifying_penalty and config.lambda_edge_policy is None:
        _add_issue(
            issues,
            "noncertifying_policy_missing",
            "lambda_edge_policy",
            "A noncertifying penalty requires explicit lambda_edge_policy provenance.",
        )
    if (
        config.allow_noncertifying_penalty
        and config.lambda_edge_policy is not None
        and not config.lambda_edge_policy.noncertifying_behavior
    ):
        _add_issue(
            issues,
            "noncertifying_behavior_missing",
            "lambda_edge_policy.noncertifying_behavior",
            "A noncertifying penalty policy must declare its intended behavior.",
        )

    _require_int_at_least(
        issues,
        "mis_execution.requested_solution_count",
        execution.requested_solution_count,
        1,
    )
    _require_int_at_least(
        issues, "mis_execution.max_distinct_samples", execution.max_distinct_samples, 1
    )
    _require_int_at_least(
        issues,
        "mis_execution.repair_max_iterations",
        execution.repair_max_iterations,
        0,
    )
    _require_int_at_least(
        issues,
        "mis_execution.exact_solver_max_variables",
        execution.exact_solver_max_variables,
        0,
    )
    _require_finite_at_least(
        issues,
        "mis_execution.minimum_candidate_jaccard_distance",
        execution.minimum_candidate_jaccard_distance,
        0.0,
    )
    if execution.minimum_candidate_jaccard_distance > 1.0:
        _add_issue(
            issues,
            "distance_above_one",
            "mis_execution.minimum_candidate_jaccard_distance",
            "minimum_candidate_jaccard_distance cannot exceed 1.",
        )
    _require_optional_timeout(
        issues,
        "mis_execution.execution_time_limit_seconds",
        execution.execution_time_limit_seconds,
    )
    _require_optional_timeout(
        issues,
        "mis_execution.compilation_time_limit_seconds",
        execution.compilation_time_limit_seconds,
    )

    _require_finite_nonnegative(
        issues, "classical_solve.time_limit_seconds", classical.time_limit_seconds
    )
    if classical.mip_gap_tolerance is not None:
        _require_finite_at_least(
            issues,
            "classical_solve.mip_gap_tolerance",
            classical.mip_gap_tolerance,
            0.0,
        )
    if classical.threads is not None:
        _require_int_at_least(issues, "classical_solve.threads", classical.threads, 1)
    _require_finite_at_least(
        issues,
        "classical_solve.primal_feasibility_tolerance",
        classical.primal_feasibility_tolerance,
        0.0,
    )
    _require_finite_at_least(
        issues,
        "classical_solve.integrality_tolerance",
        classical.integrality_tolerance,
        0.0,
    )
    _require_finite_at_least(
        issues,
        "classical_solve.objective_recomputation_absolute_tolerance",
        classical.objective_recomputation_absolute_tolerance,
        0.0,
    )
    _require_finite_at_least(
        issues,
        "classical_solve.objective_recomputation_relative_tolerance",
        classical.objective_recomputation_relative_tolerance,
        0.0,
    )

    # Embedding profile validation
    # Distinguish between: key absent (OK), key=string (validate), key=None (reject)
    compilation_params = execution.compilation_parameters
    has_embedding_profile_key = "embedding_profile" in compilation_params
    embedding_profile = compilation_params.get("embedding_profile")
    valid_profiles = ("none", "pegasus_p16", "zephyr_z12")
    hardware_profiles = ("pegasus_p16", "zephyr_z12")

    if has_embedding_profile_key:
        if embedding_profile is None:
            # Explicit None is not allowed - use "none" string or omit the key
            _add_issue(
                issues,
                "embedding_profile_explicit_none",
                "mis_execution.compilation_parameters.embedding_profile",
                "embedding_profile=None is not allowed. Use \"none\" or omit the key.",
            )
        elif not isinstance(embedding_profile, str):
            # Must be a string (reject numbers, booleans, lists, etc.)
            _add_issue(
                issues,
                "invalid_embedding_profile_type",
                "mis_execution.compilation_parameters.embedding_profile",
                f"embedding_profile must be a string, got {type(embedding_profile).__name__}.",
            )
        elif embedding_profile not in valid_profiles:
            _add_issue(
                issues,
                "invalid_embedding_profile_value",
                "mis_execution.compilation_parameters.embedding_profile",
                f"embedding_profile='{embedding_profile}' is not valid. "
                f"Allowed values: {', '.join(valid_profiles)}.",
            )
        elif embedding_profile in hardware_profiles:
            # Hardware profile requires dwave_simulated_annealing solver
            if config.mis_solver_id != "dwave_simulated_annealing":
                _add_issue(
                    issues,
                    "embedding_requires_dwave_solver",
                    "mis_execution.compilation_parameters.embedding_profile",
                    f"embedding_profile='{embedding_profile}' requires "
                    "mis_solver_id='dwave_simulated_annealing'.",
                )
            # Hardware profile requires reduction enabled
            if reduction.max_reduction_rounds == 0:
                _add_issue(
                    issues,
                    "embedding_requires_reduction",
                    "mis_execution.compilation_parameters.embedding_profile",
                    f"embedding_profile='{embedding_profile}' requires max_reduction_rounds >= 1.",
                )

    return ValidationResult.invalid(*issues) if issues else ValidationResult.valid()


def effective_timeout(
    requested_timeout_seconds: float,
    residual_end_to_end_budget_seconds: float,
    configured_end_to_end_budget_seconds: float,
) -> EffectiveTimeout:
    """Compute the effective timeout for a backend invocation.

    This function determines the actual time limit considering three inputs:
    - The requested timeout for this specific operation (e.g., classical solver limit)
    - The remaining end-to-end budget (configured budget minus elapsed time)
    - The originally configured end-to-end budget (to distinguish 0=unlimited from exhausted)

    Semantics of 0:
    - requested_timeout_seconds = 0: No limit for this operation
    - configured_end_to_end_budget_seconds = 0: No global budget limit

    Return cases:
    - Budget exhausted (remaining <= 0 with configured > 0): invalid, backend should not run
    - Both unlimited (timeout=0 and budget=0): is_unlimited=True, no time limit
    - Timeout unlimited, budget finite: use remaining budget
    - Timeout finite, budget unlimited: use timeout
    - Both finite: use minimum of timeout and remaining budget

    Args:
        requested_timeout_seconds: Per-operation limit (0 = unlimited).
        residual_end_to_end_budget_seconds: Remaining budget (may be <= 0 if exhausted).
        configured_end_to_end_budget_seconds: Original budget (0 = unlimited).

    Returns:
        EffectiveTimeout with the resolved limit, validity, and unlimited flag.
    """
    # Validate inputs - reject booleans and non-finite values
    if isinstance(requested_timeout_seconds, bool) or not math.isfinite(requested_timeout_seconds) or requested_timeout_seconds < 0:
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="invalid_requested_timeout",
                    field="requested_timeout_seconds",
                    message="Requested timeout must be a finite number >= 0.",
                )
            ),
            is_unlimited=False,
        )

    if isinstance(configured_end_to_end_budget_seconds, bool) or not math.isfinite(configured_end_to_end_budget_seconds) or configured_end_to_end_budget_seconds < 0:
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="invalid_configured_budget",
                    field="configured_end_to_end_budget_seconds",
                    message="Configured budget must be a finite number >= 0.",
                )
            ),
            is_unlimited=False,
        )

    # Residual may be negative if exhausted, but must still be finite (not NaN/inf)
    if isinstance(residual_end_to_end_budget_seconds, bool) or not math.isfinite(residual_end_to_end_budget_seconds):
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="invalid_residual_budget",
                    field="residual_end_to_end_budget_seconds",
                    message="Residual budget must be a finite number.",
                )
            ),
            is_unlimited=False,
        )

    timeout_unlimited = requested_timeout_seconds == 0
    budget_unlimited = configured_end_to_end_budget_seconds == 0

    # Case 1: Budget is configured (finite > 0) but exhausted
    if not budget_unlimited and residual_end_to_end_budget_seconds <= 0:
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="budget_exhausted",
                    field="residual_end_to_end_budget_seconds",
                    message="The end-to-end time budget has been exhausted.",
                ),
                terminal_reason=TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
            ),
            is_unlimited=False,
        )

    # Case 2: Both limits are unlimited (0)
    if timeout_unlimited and budget_unlimited:
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.valid(),
            is_unlimited=True,
        )

    # Case 3: Timeout is unlimited but budget is finite
    if timeout_unlimited:
        # Use the full remaining budget
        return EffectiveTimeout(
            timeout_seconds=residual_end_to_end_budget_seconds,
            validation=ValidationResult.valid(),
            is_unlimited=False,
        )

    # Case 4: Budget is unlimited but timeout is finite
    if budget_unlimited:
        return EffectiveTimeout(
            timeout_seconds=requested_timeout_seconds,
            validation=ValidationResult.valid(),
            is_unlimited=False,
        )

    # Case 5: Both are finite - use the minimum
    return EffectiveTimeout(
        timeout_seconds=min(requested_timeout_seconds, residual_end_to_end_budget_seconds),
        validation=ValidationResult.valid(),
        is_unlimited=False,
    )


def _add_issue(
    issues: list[ValidationIssue], code: str, field: str, message: str
) -> None:
    issues.append(ValidationIssue(code=code, field=field, message=message))


def _require_nonempty(issues: list[ValidationIssue], field: str, value: str) -> None:
    if not value.strip():
        _add_issue(issues, "blank_value", field, "Value cannot be blank.")


def _require_int_at_least(
    issues: list[ValidationIssue], field: str, value: int, minimum: int
) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        _add_issue(
            issues,
            "integer_below_minimum",
            field,
            f"Value must be an integer >= {minimum}.",
        )




def _require_finite_at_least(
    issues: list[ValidationIssue], field: str, value: float, minimum: float
) -> None:
    if not math.isfinite(value) or value < minimum:
        _add_issue(
            issues,
            "invalid_numeric_value",
            field,
            f"Value must be finite and >= {minimum}.",
        )


def _require_finite_nonnegative(
    issues: list[ValidationIssue], field: str, value: float
) -> None:
    """Require a finite value >= 0.

    Used for timeout and budget fields where 0 means 'unlimited'.
    Rejects booleans, negative values, NaN, and infinity.
    """
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        _add_issue(
            issues,
            "invalid_nonnegative_value",
            field,
            "Value must be finite and >= 0.",
        )


def _require_finite_above_zero(
    issues: list[ValidationIssue], field: str, value: float
) -> None:
    if not math.isfinite(value) or value <= 0:
        _add_issue(
            issues, "nonpositive_numeric_value", field, "Value must be finite and > 0."
        )


def _require_optional_timeout(
    issues: list[ValidationIssue], field: str, value: float | None
) -> None:
    """Validate an optional timeout where 0 means unlimited.

    Accepts None (not configured), 0 (unlimited), or positive finite values.
    Rejects booleans, negative, NaN, and infinity.
    """
    if value is not None:
        _require_finite_nonnegative(issues, field, value)


_VALID_RECOVERY_POLICIES = frozenset({"fail", "retry_with_larger_domain"})


def _validate_recovery_policy(
    issues: list[ValidationIssue], field: str, value: str
) -> None:
    if value not in _VALID_RECOVERY_POLICIES:
        _add_issue(
            issues,
            "invalid_recovery_policy",
            field,
            f"Recovery policy must be one of: {', '.join(sorted(_VALID_RECOVERY_POLICIES))}.",
        )
