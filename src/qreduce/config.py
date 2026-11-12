"""Validation helpers for immutable resolved run configuration."""

import math
from dataclasses import dataclass

from qreduce.models import ResolvedRunConfig
from qreduce.status import TerminalReason


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
    """Timeout clamped to a positive residual end-to-end budget."""

    timeout_seconds: float | None
    validation: ValidationResult


def validate_resolved_run_config(config: ResolvedRunConfig) -> ValidationResult:
    """Validate static invariants without inspecting a reduction graph."""

    issues: list[ValidationIssue] = []
    reduction = config.reduction
    execution = config.mis_execution
    classical = config.classical_solve

    _require_nonempty(issues, "schema_version", config.schema_version)
    _require_nonempty(issues, "run_identity.run_id", config.run_identity.run_id)
    _require_nonempty(issues, "mis_solver_id", config.mis_solver_id)
    _require_nonempty(
        issues, "classical_solve.classical_solver_id", classical.classical_solver_id
    )

    if reduction.max_reduction_rounds != 1:
        _add_issue(
            issues,
            "single_pass_only",
            "reduction.max_reduction_rounds",
            "The single-pass pipeline supports exactly one reduction round.",
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
    _require_finite_above_zero(
        issues,
        "reduction.max_end_to_end_runtime_seconds",
        reduction.max_end_to_end_runtime_seconds,
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

    _require_finite_above_zero(
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

    return ValidationResult.invalid(*issues) if issues else ValidationResult.valid()


def effective_timeout(
    requested_timeout_seconds: float | None,
    residual_end_to_end_budget_seconds: float,
) -> EffectiveTimeout:
    """Clamp a requested timeout to the available end-to-end time budget."""

    if (
        not math.isfinite(residual_end_to_end_budget_seconds)
        or residual_end_to_end_budget_seconds <= 0
    ):
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="nonpositive_residual_budget",
                    field="residual_end_to_end_budget_seconds",
                    message="A non-positive residual budget forbids backend invocation.",
                ),
                terminal_reason=TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
            ),
        )
    if requested_timeout_seconds is None:
        return EffectiveTimeout(
            residual_end_to_end_budget_seconds, ValidationResult.valid()
        )
    if not math.isfinite(requested_timeout_seconds) or requested_timeout_seconds <= 0:
        return EffectiveTimeout(
            timeout_seconds=None,
            validation=ValidationResult.invalid(
                ValidationIssue(
                    code="invalid_requested_timeout",
                    field="requested_timeout_seconds",
                    message="Requested timeout must be finite and greater than zero.",
                )
            ),
        )
    return EffectiveTimeout(
        timeout_seconds=min(
            requested_timeout_seconds, residual_end_to_end_budget_seconds
        ),
        validation=ValidationResult.valid(),
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
    if value is not None:
        _require_finite_above_zero(issues, field, value)
