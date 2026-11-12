"""End-to-end portfolio experiment path using QReduce's built-in solver catalog."""

import importlib.util
import json
from dataclasses import replace

import pytest

from qreduce.domains import (
    DomainValidationResult,
    LogicalVariableCounts,
    ProtectionDeclaration,
)
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.pipeline import run_single_pass
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.mwis.local_backend import LocalGreedyMISBackend
from qreduce.solving.residual import ClassicalSolverRegistry, CplexClassicalBackend
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
        "qreduce.solving.residual.cplex_backend._import_module", raise_missing_binding
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
    assert result.original_variable_counts == LogicalVariableCounts(3, 0, 3)
    assert result.residual_variable_counts == LogicalVariableCounts(
        len(result.retained_item_ids), 0, len(result.retained_item_ids)
    )
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
    assert result.domain_evaluation_metrics is None
    assert result.classical_result.requested_solver_id == "cplex"
    assert result.classical_result.effective_solver_id is None
    assert result.metrics["raw_sample_count"] == 1
    assert result.metrics["candidate_domain_size"] == len(result.retained_item_ids)
    serialized_result = result.to_dict()
    assert serialized_result["fixing_manifest"] is not None
    assert serialized_result["mis_execution_result"] is not None
    json.dumps(serialized_result)


def test_missing_counts_method_fails_before_graph(portfolio_problem: PortfolioProblem) -> None:
    class MissingCounts:
        def build_conflict_graph(self, problem):
            raise AssertionError("Graph must not be built")

    result = run_single_pass(portfolio_problem, MissingCounts(), make_config())
    assert result.run_result.stage is PipelineStage.VALIDATION
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert "describe_logical_variables" in result.run_result.diagnostic_message
    assert result.original_variable_counts is None


def test_invalid_original_counts_fail_before_graph(portfolio_problem: PortfolioProblem) -> None:
    class InvalidCounts(MeanVariancePortfolioAdapter):
        def describe_logical_variables(self, problem):
            return {"binary_free": 3}

        def build_conflict_graph(self, problem, state=None):
            raise AssertionError("Graph must not be built")

    result = run_single_pass(
        portfolio_problem, InvalidCounts(PortfolioGraphPolicy("test", "1", 0.25)), make_config()
    )
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert "LogicalVariableCounts" in result.run_result.diagnostic_message


def test_invalid_residual_counts_preserve_original_and_fail_before_solve(
    portfolio_problem: PortfolioProblem,
) -> None:
    class InvalidResidualCounts(MeanVariancePortfolioAdapter):
        def describe_logical_variables(self, problem):
            if problem is portfolio_problem:
                return LogicalVariableCounts(3, 0, 3)
            raise ValueError("residual counts unavailable")

    result = run_single_pass(
        portfolio_problem,
        InvalidResidualCounts(PortfolioGraphPolicy("test", "1", 0.25)),
        make_config(),
    )
    assert result.run_result.stage is PipelineStage.RESTRICTION
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.original_variable_counts == LogicalVariableCounts(3, 0, 3)
    assert result.residual_variable_counts is None
    assert result.classical_result is None
    assert result.fixing_manifest is not None


def test_graph_failure_retains_original_counts(portfolio_problem: PortfolioProblem) -> None:
    class BrokenGraph(MeanVariancePortfolioAdapter):
        def build_conflict_graph(self, problem, state=None):
            raise ValueError("graph failed")

    result = run_single_pass(
        portfolio_problem, BrokenGraph(PortfolioGraphPolicy("test", "1", 0.25)), make_config()
    )
    assert result.run_result.terminal_reason is TerminalReason.GRAPH_CONSTRUCTION_FAILED
    assert result.original_variable_counts == LogicalVariableCounts(3, 0, 3)
    assert result.residual_variable_counts is None


def test_counts_method_exception_is_normalized(portfolio_problem: PortfolioProblem) -> None:
    class BrokenCounts(MeanVariancePortfolioAdapter):
        def describe_logical_variables(self, problem):
            raise RuntimeError("cannot describe model")

    result = run_single_pass(
        portfolio_problem, BrokenCounts(PortfolioGraphPolicy("test", "1", 0.25)), make_config()
    )
    assert result.run_result.stage is PipelineStage.VALIDATION
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.run_result.diagnostic_message == "cannot describe model"


def test_pipeline_retains_declared_protected_items_before_applying_cap(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """A protected asset absent from the MIS sample takes precedence over the cap."""

    declaration_calls = 0

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    class ProtectedPortfolioAdapter(MeanVariancePortfolioAdapter):
        def declare_protected_items(self, problem: PortfolioProblem) -> tuple[str, ...]:
            nonlocal declaration_calls
            del problem
            declaration_calls += 1
            return ("asset-b",)

    monkeypatch.setattr(
        "qreduce.solving.residual.cplex_backend._import_module", raise_missing_binding
    )
    config = replace(
        make_config(),
        reduction=replace(make_config().reduction, candidate_domain_max_items=2),
    )

    result = run_single_pass(
        portfolio_problem,
        ProtectedPortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25)),
        config,
    )

    assert result.retained_item_ids == ("asset-b", "asset-a")
    assert result.fixing_manifest is not None
    assert result.fixing_manifest.excluded_item_ids == ("asset-c",)
    assert result.run_result.terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    assert declaration_calls == 1


def test_pipeline_fails_before_fixing_when_protected_items_exceed_cap(
    portfolio_problem: PortfolioProblem,
) -> None:
    """The pipeline never silently drops protected assets or builds a partial manifest."""

    class TooManyProtectedPortfolioAdapter(MeanVariancePortfolioAdapter):
        def declare_protected_items(self, problem: PortfolioProblem) -> tuple[str, ...]:
            del problem
            return ("asset-a", "asset-b")

    config = replace(
        make_config(),
        reduction=replace(make_config().reduction, candidate_domain_max_items=1),
    )

    result = run_single_pass(
        portfolio_problem,
        TooManyProtectedPortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
        ),
        config,
    )

    assert result.run_result.run_status is RunStatus.FAILED
    assert result.run_result.stage is PipelineStage.CANDIDATE_DOMAIN
    assert (
        result.run_result.terminal_reason
        is TerminalReason.PROTECTED_ITEMS_EXCEED_CANDIDATE_DOMAIN_CAP
    )
    assert result.retained_item_ids == ()
    assert result.fixing_manifest is None
    assert result.classical_result is None


def test_pipeline_records_best_effort_protection_excluded_by_cap(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """An incumbent best-effort protection is auditably excluded rather than silently promoted."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    class BestEffortPortfolioAdapter(MeanVariancePortfolioAdapter):
        def declare_protected_items(
            self, problem: PortfolioProblem
        ) -> ProtectionDeclaration:
            del problem
            return ProtectionDeclaration(
                incumbent_supported_item_ids=("asset-b",),
                incumbent_protection_mode="best_effort",
            )

    monkeypatch.setattr(
        "qreduce.solving.residual.cplex_backend._import_module", raise_missing_binding
    )
    config = replace(
        make_config(),
        reduction=replace(make_config().reduction, candidate_domain_max_items=1),
    )

    result = run_single_pass(
        portfolio_problem,
        BestEffortPortfolioAdapter(PortfolioGraphPolicy("integration-policy", "1", 0.25)),
        config,
    )

    asset_b_record = next(
        record
        for record in result.candidate_domain_item_records
        if record.item_id == "asset-b"
    )
    assert result.protection_declaration is not None
    assert result.protection_declaration.incumbent_protection_mode == "best_effort"
    assert asset_b_record.decision == "excluded"
    assert asset_b_record.reason == "best_effort_protection_excluded_by_cap"


def test_pipeline_rejects_protected_item_outside_reduction_graph(
    portfolio_problem: PortfolioProblem,
) -> None:
    """Adapter-declared protections must be members of the canonical graph domain."""

    class UnknownProtectedPortfolioAdapter(MeanVariancePortfolioAdapter):
        def declare_protected_items(self, problem: PortfolioProblem) -> tuple[str, ...]:
            del problem
            return ("unknown-asset",)

    result = run_single_pass(
        portfolio_problem,
        UnknownProtectedPortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
        ),
        make_config(),
    )

    assert result.run_result.run_status is RunStatus.FAILED
    assert result.run_result.stage is PipelineStage.CANDIDATE_DOMAIN
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.fixing_manifest is None


def test_pipeline_rejects_duplicate_protected_item_ids(
    portfolio_problem: PortfolioProblem,
) -> None:
    """Duplicate protection declarations are adapter failures rather than cap input."""

    class DuplicateProtectedPortfolioAdapter(MeanVariancePortfolioAdapter):
        def declare_protected_items(self, problem: PortfolioProblem) -> tuple[str, ...]:
            del problem
            return ("asset-a", "asset-a")

    result = run_single_pass(
        portfolio_problem,
        DuplicateProtectedPortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
        ),
        make_config(),
    )

    assert result.run_result.stage is PipelineStage.CANDIDATE_DOMAIN
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.fixing_manifest is None


def test_pipeline_enforces_adapter_minimum_before_building_a_manifest(
    portfolio_problem: PortfolioProblem,
) -> None:
    """An adapter cannot mark a domain valid while bypassing its declared size minimum."""

    class MinimumEnforcingPortfolioAdapter(MeanVariancePortfolioAdapter):
        def validate_candidate_domain(
            self, problem: PortfolioProblem, retained_item_ids: tuple[str, ...]
        ) -> DomainValidationResult:
            del problem, retained_item_ids
            return DomainValidationResult(True, minimum_required_items=3)

        def build_fixing_manifest(
            self, problem: PortfolioProblem, retained_item_ids: tuple[str, ...]
        ) -> object:
            del problem, retained_item_ids
            raise AssertionError("A too-small candidate domain must not build a manifest.")

    config = replace(
        make_config(),
        reduction=replace(make_config().reduction, candidate_domain_max_items=2),
    )

    result = run_single_pass(
        portfolio_problem,
        MinimumEnforcingPortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
        ),
        config,
    )

    assert result.run_result.stage is PipelineStage.CANDIDATE_DOMAIN
    assert result.run_result.terminal_reason is TerminalReason.CANDIDATE_DOMAIN_TOO_SMALL
    assert result.fixing_manifest is None
    assert result.classical_result is None


def test_pipeline_rejects_inconsistent_manifest_before_restriction(
    portfolio_problem: PortfolioProblem,
) -> None:
    """The adapter cannot restrict a problem with fixing IDs different from the requested domain."""

    class InconsistentManifestPortfolioAdapter(MeanVariancePortfolioAdapter):
        def build_fixing_manifest(
            self, problem: PortfolioProblem, retained_item_ids: tuple[str, ...]
        ):
            manifest = super().build_fixing_manifest(problem, retained_item_ids)
            return replace(manifest, retained_item_ids=(retained_item_ids[0],))

        def restrict_problem(
            self,
            problem: PortfolioProblem,
            retained_item_ids: tuple[str, ...],
            fixing_manifest: object,
        ) -> object:
            del problem, retained_item_ids, fixing_manifest
            raise AssertionError("The pipeline must reject the manifest before restriction.")

    config = replace(
        make_config(),
        reduction=replace(make_config().reduction, candidate_domain_max_items=2),
    )

    result = run_single_pass(
        portfolio_problem,
        InconsistentManifestPortfolioAdapter(
            PortfolioGraphPolicy("integration-policy", "1", 0.25)
        ),
        config,
    )

    assert result.run_result.stage is PipelineStage.RESTRICTION
    assert result.run_result.terminal_reason is TerminalReason.ADAPTER_FAILURE
    assert result.fixing_manifest is not None
    assert result.classical_result is None


def test_pipeline_supports_explicit_extension_registries(
    monkeypatch, portfolio_problem: PortfolioProblem
) -> None:
    """Applications may add IDs explicitly without changing the standard catalog."""

    def raise_missing_binding(module_name: str):
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr(
        "qreduce.solving.residual.cplex_backend._import_module", raise_missing_binding
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
        "qreduce.solving.residual.cplex_backend._import_module", raise_missing_binding
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
