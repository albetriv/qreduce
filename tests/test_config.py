"""Tests for resolved configuration validation and terminal result consistency."""

from dataclasses import replace

import pytest

from qreduce.config import effective_timeout, validate_resolved_run_config
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    PolicyProvenance,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
    RunResult,
)
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


def make_config(**changes: object) -> ResolvedRunConfig:
    """Build a complete valid resolved configuration for contract tests."""
    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(
            max_reduction_rounds=1,
            candidate_domain_min_items=1,
            candidate_domain_max_items=5,
            num_source_mis_candidates=2,
            min_reduction_ratio=0.1,
            target_binary_variables=3,
            max_end_to_end_runtime_seconds=60.0,
        ),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy(
            policy_id="standard",
            policy_version="1",
            effective_lambda_edge=2.0,
        ),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(
            requested_solution_count=2,
            random_seed=17,
            max_distinct_samples=4,
            repair_enabled=True,
            repair_max_iterations=3,
            minimum_candidate_jaccard_distance=0.25,
            exact_solver_max_variables=20,
            execution_time_limit_seconds=20.0,
            provider_parameters={"temperature": 0.5},
        ),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id="cplex",
            time_limit_seconds=30.0,
            mip_gap_tolerance=0.01,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-7,
            objective_recomputation_relative_tolerance=1e-7,
            postcheck_mode=PostcheckMode.STRICT,
        ),
        run_identity=RunIdentity(run_id="run-001"),
        policy_provenance=PolicyProvenance(
            policy_id="portfolio-policy",
            policy_version="2026-11",
            policy_hash="abc123",
            policy_source="caller",
            policy_selection_status=PolicySelectionStatus.USER_SUPPLIED,
        ),
    )
    return replace(config, **changes)


def test_valid_configuration_is_immutable_and_hashes_deterministically() -> None:
    """Resolved configuration does not expose mutable request state."""
    config = make_config()

    assert validate_resolved_run_config(config).is_valid is True
    assert config.config_hash() == config.config_hash()
    assert '"run_id":"run-001"' in config.to_canonical_json()
    with pytest.raises(TypeError):
        config.mis_execution.provider_parameters["temperature"] = 1.0


def test_zero_reduction_rounds_baseline_is_valid() -> None:
    """max_reduction_rounds=0 is valid when recovery is disabled."""
    config = make_config(
        reduction=replace(
            make_config().reduction,
            max_reduction_rounds=0,
            max_recovery_attempts=0,
            recovery_policy_on_domain_too_small="fail",
            recovery_policy_on_infeasible="fail",
        )
    )
    result = validate_resolved_run_config(config)
    assert result.is_valid is True


@pytest.mark.parametrize(
    ("config", "expected_code"),
    [
        (
            make_config(
                reduction=replace(make_config().reduction, max_reduction_rounds=-1)
            ),
            "integer_below_minimum",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction,
                    max_reduction_rounds=0,
                    max_recovery_attempts=1,
                )
            ),
            "recovery_requires_reduction",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction,
                    max_reduction_rounds=0,
                    recovery_policy_on_domain_too_small="retry_with_larger_domain",
                )
            ),
            "recovery_requires_reduction",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction,
                    max_reduction_rounds=0,
                    recovery_policy_on_infeasible="retry_with_larger_domain",
                )
            ),
            "recovery_requires_reduction",
        ),
        (
            make_config(
                reduction=replace(make_config().reduction, candidate_domain_min_items=6)
            ),
            "candidate_domain_bounds_inverted",
        ),
        (
            make_config(
                reduction=replace(make_config().reduction, target_binary_variables=1.5)
            ),
            "integer_below_minimum",
        ),
        (make_config(lambda_edge=None, lambda_edge_policy=None), "missing_lambda_edge"),
        (
            make_config(
                lambda_edge=None,
                lambda_edge_policy=LambdaEdgePolicy("standard", "1", None),
            ),
            "missing_effective_lambda_edge",
        ),
        (
            make_config(lambda_edge_policy=LambdaEdgePolicy("standard", "1", 3.0)),
            "lambda_edge_policy_mismatch",
        ),
        (
            make_config(
                allow_noncertifying_penalty=True,
                lambda_edge_policy=LambdaEdgePolicy("experimental", "1", 2.0),
            ),
            "noncertifying_behavior_missing",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction, recovery_policy_on_domain_too_small="invalid"
                )
            ),
            "invalid_recovery_policy",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction, recovery_policy_on_infeasible="unknown"
                )
            ),
            "invalid_recovery_policy",
        ),
        (
            make_config(
                reduction=replace(
                    make_config().reduction,
                    max_recovery_attempts=3,
                    recovery_policy_on_domain_too_small="fail",
                    recovery_policy_on_infeasible="fail",
                )
            ),
            "recovery_attempts_without_policy",
        ),
        # Embedding profile with no reduction
        (
            make_config(
                reduction=replace(
                    make_config().reduction,
                    max_reduction_rounds=0,
                    max_recovery_attempts=0,
                    recovery_policy_on_domain_too_small="fail",
                    recovery_policy_on_infeasible="fail",
                ),
                mis_solver_id="dwave_simulated_annealing",
                mis_execution=replace(
                    make_config().mis_execution,
                    compilation_parameters={"embedding_profile": "pegasus_p16"},
                ),
            ),
            "embedding_requires_reduction",
        ),
        # Embedding profile with wrong solver
        (
            make_config(
                mis_solver_id="local_greedy",  # Wrong solver
                mis_execution=replace(
                    make_config().mis_execution,
                    compilation_parameters={"embedding_profile": "pegasus_p16"},
                ),
            ),
            "embedding_requires_dwave_solver",
        ),
        # Invalid embedding profile value
        (
            make_config(
                mis_solver_id="dwave_simulated_annealing",
                mis_execution=replace(
                    make_config().mis_execution,
                    compilation_parameters={"embedding_profile": "invalid_profile"},
                ),
            ),
            "invalid_embedding_profile_value",
        ),
        # Non-string embedding profile type
        (
            make_config(
                mis_solver_id="dwave_simulated_annealing",
                mis_execution=replace(
                    make_config().mis_execution,
                    compilation_parameters={"embedding_profile": 123},
                ),
            ),
            "invalid_embedding_profile_type",
        ),
        # Explicit None is not allowed (use "none" string or omit the key)
        (
            make_config(
                mis_solver_id="dwave_simulated_annealing",
                mis_execution=replace(
                    make_config().mis_execution,
                    compilation_parameters={"embedding_profile": None},
                ),
            ),
            "embedding_profile_explicit_none",
        ),
    ],
)
def test_invalid_configuration_has_normalized_reason(
    config: ResolvedRunConfig,
    expected_code: str,
) -> None:
    """Static violations are observable as invalid_configuration."""
    result = validate_resolved_run_config(config)

    assert result.is_valid is False
    assert result.terminal_reason is TerminalReason.INVALID_CONFIGURATION
    assert expected_code in {issue.code for issue in result.issues}


def test_nonpositive_budget_forbids_backend_invocation() -> None:
    """No effective timeout is provided after end-to-end budget exhaustion."""
    # Budget was configured (60.0) but is now exhausted (remaining=0.0)
    timeout = effective_timeout(5.0, 0.0, 60.0)

    assert timeout.timeout_seconds is None
    assert timeout.is_unlimited is False
    assert (
        timeout.validation.terminal_reason
        is TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED
    )


def test_effective_timeout_never_exceeds_residual_budget() -> None:
    """Backend timeout is clamped to the remaining end-to-end budget."""
    # Both finite: use minimum
    timeout = effective_timeout(30.0, 4.5, 60.0)

    assert timeout.validation.is_valid is True
    assert timeout.timeout_seconds == 4.5
    assert timeout.is_unlimited is False


def test_effective_timeout_unlimited_when_both_zero() -> None:
    """When both timeout and budget are 0, the result is unlimited."""
    timeout = effective_timeout(0.0, 0.0, 0.0)

    assert timeout.validation.is_valid is True
    assert timeout.timeout_seconds is None
    assert timeout.is_unlimited is True


def test_effective_timeout_uses_remaining_when_timeout_unlimited() -> None:
    """When timeout is 0 but budget is finite, use remaining budget."""
    timeout = effective_timeout(0.0, 30.0, 60.0)

    assert timeout.validation.is_valid is True
    assert timeout.timeout_seconds == 30.0
    assert timeout.is_unlimited is False


def test_effective_timeout_uses_timeout_when_budget_unlimited() -> None:
    """When budget is 0 (unlimited) but timeout is finite, use timeout."""
    timeout = effective_timeout(10.0, 0.0, 0.0)

    assert timeout.validation.is_valid is True
    assert timeout.timeout_seconds == 10.0
    assert timeout.is_unlimited is False


def test_run_result_rejects_adoption_after_failed_postcheck() -> None:
    """Post-check and adoption remain independently represented but coherent."""
    with pytest.raises(ValueError, match="post-check failure"):
        RunResult(
            run_id="run-001",
            run_status=RunStatus.PARTIAL_SUCCESS,
            stage=PipelineStage.POSTCHECK,
            terminal_reason=TerminalReason.POSTCHECK_FAILED,
            classical_solver_status=ClassicalSolverStatus.FEASIBLE,
            postcheck_status=PostcheckStatus.FAILED,
            adoption_status=AdoptionStatus.ADOPTED,
        )


# Tests for timeout value validation

def test_validate_timeout_value_accepts_valid_values() -> None:
    """Valid timeout values pass validation."""
    from qreduce.config import validate_timeout_value

    assert validate_timeout_value(0, "budget") is None  # 0 = unlimited
    assert validate_timeout_value(0.0, "budget") is None
    assert validate_timeout_value(60.0, "budget") is None
    assert validate_timeout_value(60, "budget") is None


def test_validate_timeout_value_rejects_booleans() -> None:
    """Boolean values are rejected even though bool is a subclass of int."""
    from qreduce.config import validate_timeout_value

    error = validate_timeout_value(True, "budget")
    assert error is not None
    assert "boolean" in error.lower()

    error = validate_timeout_value(False, "budget")
    assert error is not None
    assert "boolean" in error.lower()


def test_validate_timeout_value_rejects_nan_and_infinity() -> None:
    """NaN and infinity are rejected."""
    from qreduce.config import validate_timeout_value

    error = validate_timeout_value(float("nan"), "budget")
    assert error is not None
    assert "finite" in error.lower() or "nan" in error.lower()

    error = validate_timeout_value(float("inf"), "budget")
    assert error is not None
    assert "finite" in error.lower() or "infinity" in error.lower()

    error = validate_timeout_value(float("-inf"), "budget")
    assert error is not None


def test_validate_timeout_value_rejects_negative_values() -> None:
    """Negative values are rejected."""
    from qreduce.config import validate_timeout_value

    error = validate_timeout_value(-1, "budget")
    assert error is not None
    assert ">= 0" in error

    error = validate_timeout_value(-0.001, "budget")
    assert error is not None


def test_validate_timeout_value_rejects_non_numeric_types() -> None:
    """Non-numeric types are rejected."""
    from qreduce.config import validate_timeout_value

    error = validate_timeout_value("60", "budget")
    assert error is not None
    assert "number" in error.lower()

    error = validate_timeout_value(None, "budget")
    assert error is not None


@pytest.mark.parametrize("enabled,policy", [
    (True, "disabled"), (False, "greedy_by_weight"), (True, "unknown"),
    ("false", "disabled"), (True, []),
])
def test_completion_configuration_rejects_inconsistent_or_unknown_policy(enabled, policy):
    config = make_config()
    options = replace(config.mis_execution, completion_enabled=enabled, completion_policy_id=policy)
    assert not validate_resolved_run_config(replace(config, mis_execution=options)).is_valid


def test_completion_configuration_json_preserves_opt_in():
    import json

    config = make_config()
    config = replace(config, mis_execution=replace(config.mis_execution,
                     completion_enabled=True, completion_policy_id="greedy_by_weight"))
    payload = json.loads(config.to_canonical_json())
    options = MISExecutionOptions(**payload["mis_execution"])
    assert options.completion_enabled is True
    assert options.completion_policy_id == "greedy_by_weight"
    assert validate_resolved_run_config(replace(config, mis_execution=options)).is_valid
