"""Tests for the optional local D-Wave Ocean simulated-annealing MIS backend."""

from dataclasses import replace
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
from qreduce.solving.mwis.dwave_simulated_annealing_backend import (
    DWaveSimulatedAnnealingMISBackend,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


def make_problem() -> CanonicalMWISProblem:
    """Create a small canonical MWIS QUBO for translation and sample tests."""
    graph = ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 3.0, "b": 2.0, "c": 1.0},
        edges=(("a", "b"),),
        edge_reasons={("a", "b"): "conflict"},
        graph_policy_id="test",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 4.0)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def make_compilation_request(problem: CanonicalMWISProblem) -> MISCompilationRequest:
    """Create a request matching the D-Wave simulator capability."""
    return MISCompilationRequest(
        run_id="run-001",
        round_index=0,
        node_order=problem.graph.node_ids,
        residual_time_budget_seconds=5.0,
        requested_provider_id="dwave",
        requested_backend_id="simulated_annealing",
        requested_backend_family=BackendFamily.ANNEALING,
        requested_execution_mode=ExecutionMode.LOCAL,
        required_problem_form=ProblemForm.QUBO,
    )


def test_capabilities_report_explicit_sdk_unavailability(monkeypatch) -> None:
    """Missing Ocean packages do not substitute another backend or sampler."""

    def raise_missing(module_name: str):
        raise ModuleNotFoundError(f"No module named '{module_name}'", name=module_name)

    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", raise_missing
    )

    capabilities = DWaveSimulatedAnnealingMISBackend().capabilities()

    assert capabilities.runtime_available is False
    assert capabilities.runtime_terminal_reason is TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE
    assert capabilities.supported_problem_forms == frozenset({ProblemForm.QUBO})
    assert capabilities.supported_parameter_names == frozenset(
        {"num_reads", "num_sweeps", "beta_range", "beta_schedule_type"}
    )


@pytest.mark.parametrize("params", [
    {"chain_strength": 0.75},
    {"embedding_profile": "none", "chain_strength": 0.75},
    *({"embedding_profile": "pegasus_p16", "chain_strength": value}
      for value in (None, True, False, 0, -1, float("nan"), float("inf"), "0.75")),
])
def test_reject_invalid_chain_strength_before_embedding(monkeypatch, params):
    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._load_ocean_runtime",
        lambda: (None, None),
    )

    def unexpected_embedding(*args, **kwargs):
        pytest.fail("Invalid override must not reach embedding search")

    monkeypatch.setattr("qreduce.solving.mwis.dwave_embedding.find_embedding", unexpected_embedding)
    problem = make_problem()
    request = replace(make_compilation_request(problem), compilation_parameters=params)
    result = DWaveSimulatedAnnealingMISBackend().compile(problem, request)
    assert result.compiled_job is None
    assert result.terminal_reason is TerminalReason.INVALID_CONFIGURATION
    assert "chain_strength" in result.diagnostic_message


def test_backend_compiles_qubo_and_preserves_ocean_samples(monkeypatch) -> None:
    """The adapter translates canonical QUBO terms and maps SampleSet rows by node order."""
    recorded: dict[str, object] = {}

    class FakeBQM:
        @classmethod
        def from_qubo(cls, coefficients, offset):
            recorded["coefficients"] = coefficients
            recorded["offset"] = offset
            return "fake-bqm"

    class FakeSampler:
        def sample(self, bqm, **parameters):
            recorded["bqm"] = bqm
            recorded["parameters"] = parameters
            return SimpleNamespace(
                data=lambda **kwargs: (
                    SimpleNamespace(sample={"a": 1, "b": 0, "c": 1}, energy=-4.0, num_occurrences=3),
                    SimpleNamespace(sample={"a": 0, "b": 1, "c": 1}, energy=-3.0, num_occurrences=1),
                )
            )

    def import_fake(module_name: str):
        if module_name == "dimod":
            return SimpleNamespace(BinaryQuadraticModel=FakeBQM)
        if module_name == "dwave.samplers":
            return SimpleNamespace(SimulatedAnnealingSampler=FakeSampler)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", import_fake
    )
    backend = DWaveSimulatedAnnealingMISBackend()
    problem = make_problem()
    compilation = backend.compile(problem, make_compilation_request(problem))

    assert compilation.completion_status is MISCompletionStatus.COMPLETED
    assert compilation.compiled_job is not None
    result = backend.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id="run-001",
            round_index=0,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=problem.graph.node_ids,
            random_seed=19,
            requested_solution_count=2,
            residual_time_budget_seconds=5.0,
            execution_parameters={"num_reads": 7, "num_sweeps": 20},
        ),
    )

    assert result.completion_status is MISCompletionStatus.COMPLETED
    assert recorded["coefficients"] == {
        ("a", "a"): -3.0,
        ("b", "b"): -2.0,
        ("c", "c"): -1.0,
        ("a", "b"): 4.0,
    }
    assert recorded["offset"] == 0.0
    assert recorded["bqm"] == "fake-bqm"
    assert recorded["parameters"] == {"num_reads": 7, "num_sweeps": 20, "seed": 19}
    assert tuple(sample.delta for sample in result.samples) == ((1, 0, 1), (0, 1, 1))
    assert tuple(sample.occurrence_count for sample in result.samples) == (3, 1)
    assert all(sample.backend_reported_score == energy for sample, energy in zip(result.samples, (-4.0, -3.0), strict=True))
    assert all(sample.source_provider_id == "dwave" for sample in result.samples)
    assert all(sample.source_backend_id == "simulated_annealing" for sample in result.samples)
    assert all(sample.execution_runtime_seconds is not None for sample in result.samples)
    assert all(sample.effective_compilation_parameters == {} for sample in result.samples)
    assert all(
        sample.effective_execution_parameters == {"num_reads": 7, "num_sweeps": 20, "seed": 19}
        for sample in result.samples
    )
    assert result.effective_execution_parameters == {"num_reads": 7, "num_sweeps": 20, "seed": 19}


def test_backend_rejects_mis_graph_without_silent_representation_substitution(monkeypatch) -> None:
    """The simulator only accepts its declared QUBO representation."""
    fake_runtime = lambda _: SimpleNamespace()
    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", fake_runtime
    )
    problem = make_problem()
    request = MISCompilationRequest(
        run_id="run-001",
        round_index=0,
        node_order=problem.graph.node_ids,
        residual_time_budget_seconds=5.0,
        requested_provider_id="dwave",
        requested_backend_id="simulated_annealing",
        requested_backend_family=BackendFamily.ANNEALING,
        requested_execution_mode=ExecutionMode.LOCAL,
        required_problem_form=ProblemForm.MIS_GRAPH,
    )

    result = DWaveSimulatedAnnealingMISBackend().compile(problem, request)

    assert result.compiled_job is None
    assert result.terminal_reason is TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED


@pytest.mark.parametrize(
    "backend_sample",
    (
        {"a": 1, "b": 0},
        {"a": 1, "b": 0, "c": 1, "unexpected": 0},
        {"a": 1.0, "b": 0, "c": 1},
    ),
)
def test_backend_rejects_malformed_ocean_sample_labels_and_values(monkeypatch, backend_sample) -> None:
    """Malformed provider output cannot be decoded by guessing labels or coercing values."""

    class FakeBQM:
        @classmethod
        def from_qubo(cls, coefficients, offset):
            del coefficients, offset
            return "fake-bqm"

    class FakeSampler:
        def sample(self, bqm, **parameters):
            del bqm, parameters
            return SimpleNamespace(
                data=lambda **kwargs: (
                    SimpleNamespace(sample=backend_sample, energy=-1.0, num_occurrences=1),
                )
            )

    def import_fake(module_name: str):
        if module_name == "dimod":
            return SimpleNamespace(BinaryQuadraticModel=FakeBQM)
        if module_name == "dwave.samplers":
            return SimpleNamespace(SimulatedAnnealingSampler=FakeSampler)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", import_fake
    )
    backend = DWaveSimulatedAnnealingMISBackend()
    problem = make_problem()
    compilation = backend.compile(problem, make_compilation_request(problem))
    assert compilation.compiled_job is not None

    result = backend.solve(
        compilation.compiled_job,
        MISBackendRequest(
            run_id="run-001",
            round_index=0,
            compiled_job_id=compilation.compiled_job.compiled_job_id,
            node_order=problem.graph.node_ids,
            random_seed=None,
            requested_solution_count=1,
            residual_time_budget_seconds=5.0,
        ),
    )

    assert result.samples == ()
    assert result.completion_status is MISCompletionStatus.FAILED
    assert result.terminal_reason is TerminalReason.MIS_RESULT_NORMALIZATION_FAILED



def test_solve_rejects_hardware_profile_without_embedding(monkeypatch) -> None:
    """A hardware profile job with missing embedding fails explicitly, no fallback to logical sampling."""
    sampler_called = False

    class FakeBQM:
        @classmethod
        def from_qubo(cls, coefficients, offset):
            del coefficients, offset
            return "fake-bqm"

    class SpySampler:
        def sample(self, bqm, **parameters):
            nonlocal sampler_called
            sampler_called = True
            raise AssertionError("Sampler must not be called for invalid hardware job")

    def import_fake(module_name: str):
        if module_name == "dimod":
            return SimpleNamespace(BinaryQuadraticModel=FakeBQM)
        if module_name == "dwave.samplers":
            return SimpleNamespace(SimulatedAnnealingSampler=SpySampler)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", import_fake
    )
    backend = DWaveSimulatedAnnealingMISBackend()
    problem = make_problem()

    # Compile without embedding profile first
    compilation = backend.compile(problem, make_compilation_request(problem))
    assert compilation.compiled_job is not None

    # Manually create a job that claims hardware profile but lacks embedding
    from dataclasses import replace
    fake_hardware_job = replace(
        compilation.compiled_job,
        effective_compilation_parameters={"embedding_profile": "pegasus_p16"},  # No _embedding!
    )

    result = backend.solve(
        fake_hardware_job,
        MISBackendRequest(
            run_id="run-001",
            round_index=0,
            compiled_job_id=fake_hardware_job.compiled_job_id,
            node_order=problem.graph.node_ids,
            random_seed=None,
            requested_solution_count=1,
            residual_time_budget_seconds=5.0,
        ),
    )

    assert sampler_called is False, "Sampler should not be called for invalid hardware job"
    assert result.samples == ()
    assert result.completion_status is MISCompletionStatus.FAILED
    assert result.terminal_reason is TerminalReason.MIS_EMBEDDING_FAILED
    assert "pegasus_p16" in result.diagnostic_message
    assert "embedding" in result.diagnostic_message.lower()


def test_solve_rejects_hardware_profile_with_empty_embedding(monkeypatch) -> None:
    """A hardware profile job with empty embedding fails explicitly."""
    sampler_called = False

    class FakeBQM:
        @classmethod
        def from_qubo(cls, coefficients, offset):
            del coefficients, offset
            return "fake-bqm"

    class SpySampler:
        def sample(self, bqm, **parameters):
            nonlocal sampler_called
            sampler_called = True
            raise AssertionError("Sampler must not be called for invalid hardware job")

    def import_fake(module_name: str):
        if module_name == "dimod":
            return SimpleNamespace(BinaryQuadraticModel=FakeBQM)
        if module_name == "dwave.samplers":
            return SimpleNamespace(SimulatedAnnealingSampler=SpySampler)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(
        "qreduce.solving.mwis.dwave_simulated_annealing_backend._import_module", import_fake
    )
    backend = DWaveSimulatedAnnealingMISBackend()
    problem = make_problem()

    compilation = backend.compile(problem, make_compilation_request(problem))
    assert compilation.compiled_job is not None

    from dataclasses import replace
    fake_hardware_job = replace(
        compilation.compiled_job,
        effective_compilation_parameters={
            "embedding_profile": "zephyr_z12",
            "_embedding": {},  # Empty embedding!
        },
    )

    result = backend.solve(
        fake_hardware_job,
        MISBackendRequest(
            run_id="run-001",
            round_index=0,
            compiled_job_id=fake_hardware_job.compiled_job_id,
            node_order=problem.graph.node_ids,
            random_seed=None,
            requested_solution_count=1,
            residual_time_budget_seconds=5.0,
        ),
    )

    assert sampler_called is False
    assert result.samples == ()
    assert result.completion_status is MISCompletionStatus.FAILED
    assert result.terminal_reason is TerminalReason.MIS_EMBEDDING_FAILED
