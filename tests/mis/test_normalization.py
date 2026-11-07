"""Tests for canonical sample metric recomputation and deterministic deduplication."""

from qreduce.capabilities import RuntimeCapabilities
from qreduce.mis.contracts import (
    BackendReportedScoreKind,
    MISBackendResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.mis.normalization import (
    deduplicate_raw_mis_samples,
    normalize_backend_result,
)
from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm


def make_problem() -> CanonicalMWISProblem:
    """Build a small graph where selecting both nodes violates one edge."""

    graph = ReductionGraph(
        node_ids=("a", "b"),
        node_weights={"a": 1.0, "b": 2.0},
        edges=(("a", "b"),),
        edge_reasons={("a", "b"): "conflict"},
        graph_policy_id="test",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 3.0)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def make_result(samples: tuple[RawMISSample, ...]) -> MISBackendResult:
    """Wrap samples in an otherwise successful generic backend execution result."""

    capabilities = RuntimeCapabilities(
        provider_id="provider",
        backend_id="backend",
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
    return MISBackendResult(
        samples=samples,
        requested_provider_id="provider",
        requested_backend_id="backend",
        effective_provider_id="provider",
        effective_backend_id="backend",
        backend_family=BackendFamily.CLASSICAL_HEURISTIC,
        execution_mode=ExecutionMode.LOCAL,
        capabilities_snapshot=capabilities,
        runtime_seconds=0.01,
        completion_status=MISCompletionStatus.COMPLETED,
    )


def test_normalization_recomputes_canonical_metrics_without_reinterpreting_native_score() -> None:
    """Provider score stays declared probability while core derives graph and energy facts."""

    sample = RawMISSample(
        raw_sample_id="raw-001",
        node_order=("a", "b"),
        delta=(1, 1),
        backend_reported_score=0.8,
        backend_reported_score_kind=BackendReportedScoreKind.PROBABILITY,
        raw_backend_metadata={"access_token": "secret"},
    )

    result = normalize_backend_result(make_problem(), make_result((sample,)))
    normalized = result.samples[0]

    assert result.terminal_reason is None
    assert normalized.backend_reported_score_kind is BackendReportedScoreKind.PROBABILITY
    assert normalized.canonical_qubo_energy == 0.0
    assert normalized.selection_weight == 3.0
    assert normalized.is_independent_set is False
    assert normalized.violated_edges == (("a", "b"),)
    assert normalized.raw_backend_metadata["access_token"] == "[REDACTED]"


def test_normalization_fails_explicitly_for_incompatible_node_order() -> None:
    """Provider bit ordering cannot be guessed or silently adapted by the core."""

    result = normalize_backend_result(
        make_problem(),
        make_result((RawMISSample("raw-001", ("b", "a"), (1, 0)),)),
    )

    assert result.terminal_reason.value == "mis_result_normalization_failed"
    assert result.samples == ()


def test_deduplication_aggregates_occurrences_and_uses_stable_representative_and_cap() -> None:
    """Equal delta vectors are aggregated independently of provider score or insertion order."""

    samples = (
        RawMISSample("z-id", ("a", "b"), (1, 0), occurrence_count=2),
        RawMISSample("a-id", ("a", "b"), (1, 0), occurrence_count=3),
        RawMISSample("b-id", ("a", "b"), (0, 1), occurrence_count=1),
    )

    result = deduplicate_raw_mis_samples(samples, max_distinct_samples=1)

    assert len(result.samples) == 1
    assert result.samples[0].delta == (0, 1)
    assert len(result.discarded_samples) == 1
    discarded = result.discarded_samples[0]
    assert discarded.raw_sample_id == "a-id"
    assert discarded.occurrence_count == 5
    assert discarded.source_raw_sample_ids == ("a-id", "z-id")