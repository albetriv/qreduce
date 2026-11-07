"""Tests for pre-compilation runtime capability validation."""

from dataclasses import replace

from qreduce.capabilities import RuntimeCapabilities, validate_backend_compatibility
from qreduce.models import (
    ArtifactOptions,
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISBackendSelection,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
)
from qreduce.status import (
    BackendFamily,
    ExecutionMode,
    FallbackPolicy,
    PostcheckMode,
    ProblemForm,
    TerminalReason,
)


def make_config(**changes: object) -> ResolvedRunConfig:
    """Build a complete valid resolved configuration for capability tests."""

    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 5, 2, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_backend=MISBackendSelection(
            "local",
            "heuristic",
            BackendFamily.CLASSICAL_HEURISTIC,
            ExecutionMode.LOCAL,
            FallbackPolicy.FAIL,
        ),
        mis_execution=MISExecutionOptions(2, 17, 4, True, 3, 0.25, 20, provider_parameters={"temperature": 0.5}),
        classical_solve=ClassicalSolveOptions(
            "cplex", 30.0, 0.01, 1, False, 1e-6, 1e-6, 1e-7, 1e-7, PostcheckMode.STRICT
        ),
        artifacts=ArtifactOptions("run-001", "1.0", "0.1.0", "caller_supplied", True),
    )
    return replace(config, **changes)


def make_capabilities(**changes: object) -> RuntimeCapabilities:
    """Build a matching available local MIS capability."""

    values: dict[str, object] = {
        "provider_id": "local",
        "backend_id": "heuristic",
        "backend_family": make_config().mis_backend.backend_family,
        "execution_mode": make_config().mis_backend.execution_mode,
        "runtime_available": True,
        "supported_problem_forms": frozenset({ProblemForm.QUBO}),
        "supports_random_seed": True,
        "supports_solution_count": True,
        "supports_execution_time_limit": True,
        "supports_compilation_time_limit": False,
        "supports_async_execution": False,
        "supports_cancellation": False,
        "supported_parameter_names": frozenset({"temperature"}),
    }
    values.update(changes)
    return RuntimeCapabilities(**values)  # type: ignore[arg-type]


def test_matching_capability_is_accepted_before_compilation() -> None:
    """An available backend accepting all requested features validates successfully."""

    result = validate_backend_compatibility(make_config(), make_capabilities(), ProblemForm.QUBO)

    assert result.is_valid is True


def test_unsupported_backend_parameter_is_rejected() -> None:
    """Unknown provider parameters do not reach compilation by default."""

    config = make_config(
        mis_execution=MISExecutionOptions(
            requested_solution_count=2,
            random_seed=17,
            max_distinct_samples=4,
            repair_enabled=True,
            repair_max_iterations=3,
            minimum_candidate_jaccard_distance=0.25,
            exact_solver_max_variables=20,
            provider_parameters={"unknown_option": True},
        )
    )

    result = validate_backend_compatibility(config, make_capabilities(), ProblemForm.QUBO)

    assert result.is_valid is False
    assert result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert {issue.field for issue in result.issues} == {"provider_parameters"}


def test_unavailable_backend_produces_explicit_failure_without_fallback() -> None:
    """Runtime availability remains separate from the requested selection."""

    result = validate_backend_compatibility(
        make_config(),
        make_capabilities(
            runtime_available=False,
            runtime_terminal_reason=TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
        ),
        ProblemForm.QUBO,
    )

    assert result.is_valid is False
    assert result.terminal_reason is TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE


def test_unsupported_problem_form_is_rejected_before_compilation() -> None:
    """A configured form cannot be silently converted to another representation."""

    result = validate_backend_compatibility(make_config(), make_capabilities(), ProblemForm.ISING)

    assert result.is_valid is False
    assert result.terminal_reason is TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED


def test_exact_solver_diagnostic_limit_does_not_constrain_heuristic_backend_capability() -> None:
    """The exact diagnostic limit is unrelated to an operational backend size limit."""

    result = validate_backend_compatibility(
        make_config(),
        make_capabilities(maximum_variables=1),
        ProblemForm.QUBO,
    )

    assert result.is_valid is True