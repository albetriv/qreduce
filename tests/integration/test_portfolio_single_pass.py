"""End-to-end reference portfolio path using local greedy MWIS and requested CPLEX."""

import json

import pytest

from qreduce.domains.portfolio import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.models import (
    ArtifactOptions,
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
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
    """Build the deterministic solver configuration used by the reference path."""

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
        artifacts=ArtifactOptions("portfolio-integration", "1.0", "0.1.0", "caller_supplied", True),
    )


def test_portfolio_single_pass_reaches_explicit_cplex_unavailable_failure(monkeypatch, portfolio_problem: PortfolioProblem) -> None:
    """The reference adapter and greedy solver run before an unavailable CPLEX solve fails explicitly."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr("qreduce.classical.cplex_backend._import_module", raise_missing_binding)
    config = make_config()
    adapter = MeanVariancePortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25))

    result = run_single_pass(portfolio_problem, adapter, config)

    assert result.retained_item_ids
    assert result.fixing_manifest is not None
    assert result.selected_mis_samples
    assert result.mis_compilation_result is not None
    assert result.mis_execution_result is not None
    assert result.run_result.run_status is RunStatus.FAILED
    assert result.run_result.stage is PipelineStage.CLASSICAL
    assert result.run_result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    assert result.run_result.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE
    assert result.classical_result is not None
    assert result.classical_result.requested_solver_id == "cplex"
    assert result.classical_result.effective_solver_id is None
    assert result.metrics["raw_sample_count"] == 1
    assert result.metrics["candidate_domain_size"] == len(result.retained_item_ids)
    serialized_result = result.to_dict()
    assert serialized_result["fixing_manifest"] is not None
    assert serialized_result["mis_execution_result"] is not None
    json.dumps(serialized_result)