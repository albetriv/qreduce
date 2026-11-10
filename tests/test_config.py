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


@pytest.mark.parametrize(
    ("config", "expected_code"),
    [
        (
            make_config(
                reduction=replace(make_config().reduction, max_reduction_rounds=2)
            ),
            "single_pass_only",
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

    timeout = effective_timeout(5.0, 0.0)

    assert timeout.timeout_seconds is None
    assert (
        timeout.validation.terminal_reason
        is TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED
    )


def test_effective_timeout_never_exceeds_residual_budget() -> None:
    """Backend timeout is clamped to the remaining end-to-end budget."""

    timeout = effective_timeout(30.0, 4.5)

    assert timeout.validation.is_valid is True
    assert timeout.timeout_seconds == 4.5


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
