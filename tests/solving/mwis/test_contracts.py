"""Tests for provider-neutral MIS contracts and their state invariants."""

import pytest

from qreduce.capabilities import RuntimeCapabilities
from qreduce.solving.mwis.contracts import (
    BackendReportedScoreKind,
    MISBackendRequest,
    MISBackendResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


def make_capabilities() -> RuntimeCapabilities:
    """Build a minimal available local capability for serializable contracts."""

    return RuntimeCapabilities(
        provider_id="local",
        backend_id="greedy_mis",
        backend_family=BackendFamily.CLASSICAL_HEURISTIC,
        execution_mode=ExecutionMode.LOCAL,
        runtime_available=True,
        supported_problem_forms=frozenset({ProblemForm.MIS_GRAPH}),
        supports_random_seed=True,
        supports_solution_count=True,
        supports_execution_time_limit=True,
        supports_compilation_time_limit=True,
        supports_async_execution=False,
        supports_cancellation=False,
    )


def test_raw_sample_is_binary_redacted_and_never_certified_by_its_contract() -> None:
    """Raw samples preserve backend data but expose no optimality claim."""

    sample = RawMISSample(
        raw_sample_id="sample-001",
        node_order=("a", "b"),
        delta=(1, 0),
        backend_reported_score=0.75,
        backend_reported_score_kind=BackendReportedScoreKind.PROBABILITY,
        raw_backend_metadata={"api_token": "secret", "endpoint": "https://example.test?token=abc&id=7"},
    )

    assert sample.to_dict()["raw_backend_metadata"]["api_token"] == "[REDACTED]"
    assert "secret" not in sample.to_dict()["raw_backend_metadata"]["endpoint"]
    assert "is_certified_mwis_optimum" not in sample.to_dict()
    with pytest.raises(TypeError):
        sample.raw_backend_metadata["another"] = "value"


def test_failed_execution_requires_a_normalized_terminal_reason() -> None:
    """Failure state cannot silently omit the reason needed by pipeline artifacts."""

    with pytest.raises(ValueError, match="requires a terminal reason"):
        MISBackendResult(
            samples=(),
            requested_provider_id="local",
            requested_backend_id="greedy_mis",
            effective_provider_id="local",
            effective_backend_id="greedy_mis",
            backend_family=BackendFamily.CLASSICAL_HEURISTIC,
            execution_mode=ExecutionMode.LOCAL,
            capabilities_snapshot=make_capabilities(),
            runtime_seconds=0.0,
            completion_status=MISCompletionStatus.FAILED,
        )

    result = MISBackendResult(
        samples=(),
        requested_provider_id="local",
        requested_backend_id="greedy_mis",
        effective_provider_id="local",
        effective_backend_id="greedy_mis",
        backend_family=BackendFamily.CLASSICAL_HEURISTIC,
        execution_mode=ExecutionMode.LOCAL,
        capabilities_snapshot=make_capabilities(),
        runtime_seconds=0.0,
        completion_status=MISCompletionStatus.FAILED,
        terminal_reason=TerminalReason.MIS_EXECUTION_FAILED,
    )

    assert result.to_dict()["terminal_reason"] == "mis_execution_failed"


def test_execution_request_serialization_redacts_sensitive_provider_parameters() -> None:
    """Execution artifacts cannot expose secret-bearing provider parameters."""

    request = MISBackendRequest(
        run_id="run-001",
        round_index=0,
        compiled_job_id="job-001",
        node_order=("a",),
        random_seed=7,
        requested_solution_count=1,
        residual_time_budget_seconds=1.0,
        execution_parameters={"api_token": "secret"},
    )

    assert request.to_dict()["execution_parameters"]["api_token"] == "[REDACTED]"