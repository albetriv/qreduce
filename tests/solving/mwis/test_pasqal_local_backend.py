"""Strict geometry and optional Pulser local round-trip tests."""

from itertools import combinations
from types import SimpleNamespace

import pytest

from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.solving.mwis.contracts import (
    MISBackendRequest,
    MISCompilationRequest,
    MISCompletionStatus,
)
from qreduce.solving.mwis.pasqal_local_backend import (
    LOCAL_QUTIP_MAX_ATOMS,
    PasqalLocalMISBackend,
)
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout, search_layout
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


def problem():
    graph = ReductionGraph(
        ("b", "a"),
        {"a": 1, "b": 2},
        (("a", "b"),),
        {("a", "b"): "conflict"},
        "test",
        "1",
    )
    qubo = build_mwis_qubo(graph, 3)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def test_geometry_boundaries_and_exhaustion():
    graph = problem().graph
    assert diagnose_layout(graph, {"a": (0, 0), "b": (9, 0)}, 10, 1)["valid"]
    diag = diagnose_layout(graph, {"a": (0, 0), "b": (9.5, 0)}, 10, 1)
    assert not diag["valid"]
    assert diag["missing_edges"] == []
    assert diag["margin_pairs"] == [("a", "b")]
    with pytest.raises(ValueError, match="layout_search_exhausted"):
        search_layout(graph, 10, 1, attempts=2, accept=lambda _: False)


def compilation_request(p):
    return MISCompilationRequest(
        "run",
        0,
        p.graph.node_ids,
        0,
        "pasqal",
        "pasqal_local",
        BackendFamily.NEUTRAL_ATOM,
        ExecutionMode.LOCAL,
        ProblemForm.MIS_GRAPH,
    )


@pytest.mark.parametrize(
    "edges",
    [tuple(combinations("abcd", 2)), (("a", "b"), ("b", "c"), ("c", "d"), ("a", "d"))],
)
def test_neighbor_guided_layout(edges):
    ids = tuple("abcd")
    graph = ReductionGraph(
        ids, dict.fromkeys(ids, 1), edges, dict.fromkeys(edges, "conflict"), "test", "1"
    )
    coords, diag = search_layout(graph, 10, 1, min_distance=5)
    assert diag["method"] == "neighbor_guided"
    assert diagnose_layout(graph, coords, 10, 1)["valid"]


def test_real_local_roundtrip():
    pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    compiled = backend.compile(p, compilation_request(p))
    assert compiled.completion_status is MISCompletionStatus.COMPLETED, (
        compiled.diagnostic_message
    )
    job = compiled.compiled_job
    assert job.provider_payload["node_order"] == ["b", "a"]
    execution = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 5, 0
    )
    result = backend.solve(job, execution)
    assert result.completion_status is MISCompletionStatus.COMPLETED, (
        result.diagnostic_message
    )
    assert sum(sample.occurrence_count for sample in result.samples) == 5
    assert all(sample.node_order == ("b", "a") for sample in result.samples)
    assert result.effective_execution_parameters == {"shots": 5}


def test_reordered_asymmetric_bitstring(monkeypatch):
    simulation = pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    job = backend.compile(p, compilation_request(p)).compiled_job
    assert job is not None
    monkeypatch.setattr(
        simulation,
        "QutipBackendV2",
        lambda *args, **kwargs: SimpleNamespace(
            run=lambda: SimpleNamespace(
                atom_order=("q1", "q0"), final_bitstrings={"10": 7}
            )
        ),
    )
    request = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 1, 0, {"shots": 7}
    )
    result = backend.solve(job, request)
    assert result.completion_status is MISCompletionStatus.COMPLETED
    (sample,) = result.samples
    assert sample.node_order == ("b", "a")
    assert sample.delta == (0, 1)
    assert sample.occurrence_count == 7


def test_compile_rejects_graph_over_local_limit():
    pytest.importorskip("pulser_simulation")
    ids = tuple(f"n{i}" for i in range(LOCAL_QUTIP_MAX_ATOMS + 1))
    graph = ReductionGraph(ids, dict.fromkeys(ids, 1), (), {}, "test", "1")
    qubo = build_mwis_qubo(graph, 3)
    p = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))
    result = PasqalLocalMISBackend().compile(p, compilation_request(p))
    assert result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert result.compiled_job is None


def test_portfolio_pasqal_options_keep_all_distinct_samples():
    pytest.importorskip("numpy")
    from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs
    from qreduce.experiments.portfolio_sr.execution import _build_mis_execution_options

    mv = build_synthetic_portfolio_inputs(
        "test", asset_count=6, mis_solver_id="pasqal_local", pasqal_shots=23
    )
    sr = _build_mis_execution_options(mis_solver_id="pasqal_local", pasqal_shots=23)
    for options in (mv.config.mis_execution, sr):
        assert options.max_distinct_samples == 23
        assert options.provider_parameters == {"shots": 23}
