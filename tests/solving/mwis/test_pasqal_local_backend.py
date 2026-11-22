"""Strict geometry, parametric annealing, and presolve tests for Pasqal backend."""

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
    PAYLOAD_VERSION,
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


def edgeless_problem(node_count: int = 5):
    """Create an edgeless problem for presolve testing."""
    node_ids = tuple(f"n{i}" for i in range(node_count))
    node_weights = {nid: 1.0 + i * 0.1 for i, nid in enumerate(node_ids)}
    graph = ReductionGraph(
        node_ids,
        node_weights,
        (),  # No edges
        {},
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


def compilation_request(p, use_legacy_pulse=False):
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
        compilation_parameters={"use_legacy_pulse": use_legacy_pulse},
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
    # Verify new payload fields
    assert job.provider_payload.get("presolve_applied") is False
    assert "pulse_strategy" in job.provider_payload
    assert "weight_encoding_mode" in job.provider_payload
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


def test_legacy_pulse_mode():
    """Test that legacy pulse mode can be explicitly enabled."""
    pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    compiled = backend.compile(p, compilation_request(p, use_legacy_pulse=True))
    assert compiled.completion_status is MISCompletionStatus.COMPLETED

    job = compiled.compiled_job
    pulse_strategy = job.provider_payload.get("pulse_strategy", {})
    assert pulse_strategy.get("strategy_id") == "constant"


def test_smoothed_annealing_default():
    """Test that smoothed annealing is the default strategy."""
    pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    compiled = backend.compile(p, compilation_request(p, use_legacy_pulse=False))
    assert compiled.completion_status is MISCompletionStatus.COMPLETED

    job = compiled.compiled_job
    pulse_strategy = job.provider_payload.get("pulse_strategy", {})
    assert pulse_strategy.get("strategy_id") == "smoothed_annealing"


def test_presolve_edgeless_graph():
    """Edgeless graphs should be presolved without backend execution."""
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(5)
    compiled = backend.compile(p, compilation_request(p))

    assert compiled.completion_status is MISCompletionStatus.COMPLETED
    job = compiled.compiled_job

    # Should use presolve path
    assert job.provider_payload_type == "pasqal.presolve"
    assert job.provider_payload["presolve_applied"] is True
    assert job.provider_payload["presolve_size"] == 5  # All nodes selected
    assert job.provider_payload["is_certified_optimal"] is True
    assert job.effective_backend_id == "presolve_exact"


def test_presolve_execution_returns_optimal():
    """Solving a presolved job should return the optimal solution.

    The presolve result is deterministic, not statistical, so:
    - occurrence_count=1 (not shots) because it's a single exact result
    - source_provider_id="qreduce" (not "pasqal") because it's computed by QReduce
    - effective_execution_parameters includes both requested_shots and effective_shots
    """
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(5)
    compiled = backend.compile(p, compilation_request(p))
    job = compiled.compiled_job

    execution = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0
    )
    result = backend.solve(job, execution)

    assert result.completion_status is MISCompletionStatus.COMPLETED
    assert len(result.samples) == 1  # Single optimal sample

    sample = result.samples[0]
    assert sample.delta == (1, 1, 1, 1, 1)  # All selected
    # Presolve is deterministic: 1 exact result, not 10 statistical samples
    assert sample.occurrence_count == 1
    assert sample.source_provider_id == "qreduce"  # Computed by QReduce, not Pasqal
    assert "presolve" in sample.source_backend_id
    # Requested vs effective shots are recorded for auditability
    assert sample.effective_execution_parameters["requested_shots"] == 10
    assert sample.effective_execution_parameters["effective_shots"] == 0


def test_presolve_validates_job_identity():
    """Presolve path should reject mismatched job identity, same as Pulser path."""
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(5)
    compiled = backend.compile(p, compilation_request(p))
    job = compiled.compiled_job

    # Mismatched run_id
    bad_request = MISBackendRequest(
        "WRONG_RUN_ID", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0
    )
    result = backend.solve(job, bad_request)
    assert result.completion_status is MISCompletionStatus.FAILED
    assert result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert "identity" in result.diagnostic_message.lower()


def test_presolve_validates_shots_parameter():
    """Presolve path should reject invalid shots, same as Pulser path."""
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(5)
    compiled = backend.compile(p, compilation_request(p))
    job = compiled.compiled_job

    # shots=0 is invalid
    bad_request = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0,
        execution_parameters={"shots": 0}
    )
    result = backend.solve(job, bad_request)
    assert result.completion_status is MISCompletionStatus.FAILED
    assert result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH


def test_presolve_rejects_random_seed():
    """Presolve path should reject random_seed, same as Pulser path."""
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(5)
    compiled = backend.compile(p, compilation_request(p))
    job = compiled.compiled_job

    bad_request = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids,
        random_seed=42,  # Not supported
        requested_solution_count=10,
        residual_time_budget_seconds=0
    )
    result = backend.solve(job, bad_request)
    assert result.completion_status is MISCompletionStatus.FAILED
    assert "random_seed" in result.diagnostic_message.lower()


def test_presolve_12_node_portfolio_scenario():
    """Test the exact scenario from the plan: 12 nodes, no edges."""
    backend = PasqalLocalMISBackend()
    p = edgeless_problem(12)

    # This is the problem: before fix, Pasqal would select only 8/12
    compiled = backend.compile(p, compilation_request(p))
    assert compiled.completion_status is MISCompletionStatus.COMPLETED

    job = compiled.compiled_job
    assert job.provider_payload["presolve_size"] == 12  # All 12 selected!

    # Execute to verify
    execution = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 100, 0
    )
    result = backend.solve(job, execution)

    sample = result.samples[0]
    assert sum(sample.delta) == 12  # All 12 nodes selected


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
    # Need at least one edge to avoid presolve
    edges = (("n0", "n1"),)
    graph = ReductionGraph(ids, dict.fromkeys(ids, 1), edges, {("n0", "n1"): "conflict"}, "test", "1")
    qubo = build_mwis_qubo(graph, 3)
    p = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))
    result = PasqalLocalMISBackend().compile(p, compilation_request(p))
    assert result.terminal_reason is TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
    assert result.compiled_job is None


def test_payload_version():
    """Verify payload version is updated."""
    assert PAYLOAD_VERSION >= 2  # Version 2 adds pulse_strategy and presolve


def test_weight_encoding_mode_in_samples():
    """Sample metadata should include weight encoding mode."""
    pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    compiled = backend.compile(p, compilation_request(p))
    job = compiled.compiled_job

    execution = MISBackendRequest(
        "run", 0, job.compiled_job_id, p.graph.node_ids, None, 5, 0
    )
    result = backend.solve(job, execution)

    for sample in result.samples:
        exec_params = sample.effective_execution_parameters
        assert "weight_encoding_mode" in exec_params
        assert exec_params["weight_encoding_mode"] == "classical_ranking"


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


def test_compilation_includes_geometry_diagnostics():
    """Compilation payload should include geometry and physical vs canonical diagnostics."""
    pytest.importorskip("pulser_simulation")
    backend = PasqalLocalMISBackend()
    p = problem()
    compiled = backend.compile(p, compilation_request(p))

    assert compiled.completion_status is MISCompletionStatus.COMPLETED
    payload = compiled.compiled_job.provider_payload

    # Should have geometry diagnostics
    assert "geometry_diagnostics" in payload
    geom = payload["geometry_diagnostics"]
    assert "is_valid" in geom
    assert "fidelity_score" in geom
    assert "graph_edge_count" in geom
    assert geom["graph_edge_count"] == 1  # problem() has one edge

    # Should have physical vs canonical comparison (small graph)
    assert "physical_vs_canonical" in payload
    comparison = payload["physical_vs_canonical"]
    if comparison is not None:  # Only present for small graphs
        assert "ground_state_matches_optimum" in comparison
        assert "physical_ground_state" in comparison
        assert "canonical_optimum" in comparison


def test_geometry_diagnostics_detects_interaction_issues():
    """Geometry diagnostics should detect when interactions don't match graph structure."""
    pytest.importorskip("pulser_simulation")
    from qreduce.solving.mwis.geometry_diagnostics import (
        diagnose_geometry_fidelity,
    )

    # Create a graph where edges don't correspond to strong interactions
    # (nodes far apart despite being connected)
    ids = tuple("abc")
    graph = ReductionGraph(
        ids,
        dict.fromkeys(ids, 1),
        (("a", "b"),),  # a-b are connected
        {("a", "b"): "conflict"},
        "test",
        "1",
    )

    # Place atoms such that a-b are far (weak interaction despite edge)
    # and b-c are close (strong interaction despite no edge)
    coords = {
        "a": (0.0, 0.0),
        "b": (20.0, 0.0),  # Far from a - weak interaction
        "c": (21.0, 0.0),  # Close to b - strong interaction
    }

    diag = diagnose_geometry_fidelity(graph, coords, interaction_threshold=1.0)

    # Should detect problems
    assert diag.weak_edge_count >= 1 or diag.spurious_interaction_count >= 1
    assert len(diag.warnings) > 0


@pytest.mark.parametrize("change", [
    {"presolve_delta": [0, 0, 0, 0, 0]}, {"is_certified_optimal": False},
    {"node_order": []}, {"presolve_weight": 999}, {"presolve_size": 0},
    {"presolve_delta": [True] * 5},
])
def test_presolve_rejects_tampered_payload(change):
    from dataclasses import replace
    backend = PasqalLocalMISBackend()
    p = edgeless_problem()
    job = backend.compile(p, compilation_request(p)).compiled_job
    job = replace(job, provider_payload={**job.provider_payload, **change})
    request = MISBackendRequest("run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0)
    assert backend.solve(job, request).completion_status is MISCompletionStatus.FAILED


def test_standard_pair_has_independent_physical_ground_states():
    pytest.importorskip("pulser")
    backend = PasqalLocalMISBackend()
    p = problem()
    job = backend.compile(p, compilation_request(p)).compiled_job
    assert job.provider_payload["physical_vs_canonical"]["all_ground_states_independent"]
    assert job.provider_payload["geometry_diagnostics"]["c6_coefficient"] > 865000
    assert job.provider_payload["pulse_strategy"]["final_detuning_rad_per_us"] < 10


def test_unsafe_physics_rejected_unless_experimental(monkeypatch):
    from dataclasses import replace

    from qreduce.solving.mwis import pasqal_local_backend as module
    pytest.importorskip("pulser")
    original = module.compare_physical_vs_canonical
    monkeypatch.setattr(module, "compare_physical_vs_canonical",
                        lambda *a, **kw: replace(original(*a, **kw), all_ground_states_independent=False))
    backend = PasqalLocalMISBackend()
    p = problem()
    request = compilation_request(p)
    assert backend.compile(p, request).completion_status is MISCompletionStatus.FAILED
    experimental = replace(request, compilation_parameters={"allow_unfaithful_physics": True})
    job = backend.compile(p, experimental).compiled_job
    assert job.provider_payload["experimental_physics_override"] is True


@pytest.mark.parametrize("params", [{"layout_attempts": 0}, {"layout_attempts": True},
                                    {"use_legacy_pulse": "false"}])
def test_presolve_does_not_bypass_compilation_parameter_validation(params):
    from dataclasses import replace
    backend = PasqalLocalMISBackend()
    p = edgeless_problem()
    result = backend.compile(p, replace(compilation_request(p), compilation_parameters=params))
    assert result.completion_status is MISCompletionStatus.FAILED


def test_presolve_rejects_old_payload_version():
    from dataclasses import replace
    backend = PasqalLocalMISBackend()
    p = edgeless_problem()
    job = backend.compile(p, compilation_request(p)).compiled_job
    job = replace(job, provider_payload_version=PAYLOAD_VERSION - 1)
    request = MISBackendRequest("run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0)
    assert backend.solve(job, request).completion_status is MISCompletionStatus.FAILED
