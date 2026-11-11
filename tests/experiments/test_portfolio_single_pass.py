"""End-to-end portfolio experiment path using QReduce's built-in solver catalog."""

import importlib.util
import json
from dataclasses import replace

import pytest

from qreduce.classical import ClassicalSolverRegistry, CplexClassicalBackend
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.mis import MISSolverRegistry
from qreduce.mis.local_backend import LocalGreedyMISBackend
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.pipeline import run_single_pass
from qreduce.status import (
    ClassicalSolverStatus,
    PipelineStage,
    PostcheckMode,
    RunStatus,
    TerminalReason,
)

pytestmark = pytest.mark.integration


def make_config() -> ResolvedRunConfig:
    """Build the deterministic solver configuration used by this experiment path."""

    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 3, 1, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id="cplex",
            time_limit_seconds=10.0,
            mip_gap_tolerance=None,
            threads=1,
            model_export_enabled=False,
            primal_feasibility_tolerance=1e-6,
            integrality_tolerance=1e-6,
            objective_recomputation_absolute_tolerance=1e-6,
            objective_recomputation_relative_tolerance=1e-6,
            postcheck_mode=PostcheckMode.STRICT,
            random_seed=7,
        ),
        run_identity=RunIdentity("portfolio-integration"),
    )


def test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """The experiment's selected solvers run before CPLEX absence fails explicitly."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr(
        "qreduce.classical.cplex_backend._import_module", raise_missing_binding
    )
    config = make_config()
    adapter = MeanVariancePortfolioAdapter(
        PortfolioGraphPolicy("integration-policy", "1", 0.25)
    )

    result = run_single_pass(
        portfolio_problem,
        adapter,
        config,
    )

    assert result.retained_item_ids
    assert result.fixing_manifest is not None
    assert result.selected_mis_samples
    assert result.mis_compilation_result is not None
    assert result.mis_execution_result is not None
    assert result.run_result.run_status is RunStatus.FAILED
    assert result.run_result.stage is PipelineStage.CLASSICAL
    assert (
        result.run_result.terminal_reason
        is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    )
    assert (
        result.run_result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    )
    assert result.classical_result is not None
    assert result.classical_result.requested_solver_id == "cplex"
    assert result.classical_result.effective_solver_id is None
    assert result.metrics["raw_sample_count"] == 1
    assert result.metrics["candidate_domain_size"] == len(result.retained_item_ids)
    serialized_result = result.to_dict()
    assert serialized_result["fixing_manifest"] is not None
    assert serialized_result["mis_execution_result"] is not None
    json.dumps(serialized_result)


def test_pipeline_supports_explicit_extension_registries(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """Applications may add IDs explicitly without changing the standard catalog."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr(
        "qreduce.classical.cplex_backend._import_module", raise_missing_binding
    )
    mis_registry = MISSolverRegistry(include_builtins=False)
    mis_registry.register("caller_mis", LocalGreedyMISBackend)

    class CallerClassicalBackend(CplexClassicalBackend):
        solver_id = "caller_classical"

    classical_registry = ClassicalSolverRegistry(include_builtins=False)
    classical_registry.register("caller_classical", CallerClassicalBackend)
    config = make_config()
    config = replace(
        config,
        mis_solver_id="caller_mis",
        classical_solve=replace(config.classical_solve, classical_solver_id="caller_classical"),
    )

    result = run_single_pass(
        portfolio_problem,
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25)),
        config,
        mis_solver_registry=mis_registry,
        classical_solver_registry=classical_registry,
    )

    assert result.mis_execution_result is not None
    assert result.run_result.stage is PipelineStage.CLASSICAL
    assert result.classical_result is not None
    assert result.classical_result.requested_solver_id == "caller_classical"
    assert result.classical_result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    assert result.classical_result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE


@pytest.mark.requires_dwave_simulator
@pytest.mark.skipif(
    importlib.util.find_spec("dimod") is None or importlib.util.find_spec("dwave.samplers") is None,
    reason="requires the optional D-Wave Ocean local simulator dependencies",
)
def test_pipeline_selects_dwave_simulated_annealing_qubo_backend(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """A built-in D-Wave simulator ID receives the QUBO form and provider parameters."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr(
        "qreduce.classical.cplex_backend._import_module", raise_missing_binding
    )
    config = make_config()
    config = replace(
        config,
        mis_solver_id="dwave_simulated_annealing",
        mis_execution=replace(
            config.mis_execution,
            provider_parameters={"num_reads": 8, "num_sweeps": 20},
        ),
    )

    result = run_single_pass(
        portfolio_problem,
        MeanVariancePortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25)),
        config,
    )

    assert result.mis_compilation_result is not None
    assert result.mis_compilation_result.compiled_job is not None
    assert result.mis_compilation_result.compiled_job.problem_form.value == "qubo"
    assert result.mis_execution_result is not None
    assert result.mis_execution_result.effective_provider_id == "dwave"
    assert result.mis_execution_result.effective_backend_id == "simulated_annealing"
    assert result.mis_execution_result.effective_execution_parameters["num_reads"] == 8
    assert result.mis_execution_result.effective_execution_parameters["num_sweeps"] == 20
    assert result.selected_mis_samples
    assert result.run_result.stage is PipelineStage.CLASSICAL
