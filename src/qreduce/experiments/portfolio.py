"""Synthetic portfolio experiment factory, runner and filesystem-backed analysis data."""

import argparse
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from qreduce.experiments.artifacts import (
    ExperimentArtifactError,
    ExperimentRunArtifacts,
    load_experiment_run,
)
from qreduce.experiments.portfolio_domain import (
    MeanVariancePortfolioAdapter,
    PortfolioGraphPolicy,
    PortfolioProblem,
)
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.mwis import ReductionGraph
from qreduce.status import PostcheckMode

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_domain.models import (
        SyntheticPortfolioGenerationPolicy,
    )

SYNTHETIC_PORTFOLIO_EXPERIMENT_ID = "synthetic-portfolio-single-pass"


def default_graph_policy(
    edge_mode: str = "near_duplicate",
    *,
    correlation_threshold: float = 0.90,
    near_duplicate_max_relative_return_difference: float = 0.10,
    near_duplicate_max_relative_variance_difference: float = 0.10,
) -> PortfolioGraphPolicy:
    """Create a default graph policy with the specified edge mode.

    Args:
        edge_mode: Either "correlation_only" or "near_duplicate"
        correlation_threshold: Absolute correlation threshold for edges
        near_duplicate_max_relative_return_difference: Max relative return diff (near_duplicate only)
        near_duplicate_max_relative_variance_difference: Max relative variance diff (near_duplicate only)

    Returns:
        PortfolioGraphPolicy configured with the specified parameters
    """
    return PortfolioGraphPolicy(
        policy_id=f"synthetic-portfolio-{edge_mode}",
        policy_version="1",
        correlation_absolute_threshold=correlation_threshold,
        edge_mode=edge_mode,  # type: ignore[arg-type]
        near_duplicate_max_relative_return_difference=near_duplicate_max_relative_return_difference,
        near_duplicate_max_relative_variance_difference=near_duplicate_max_relative_variance_difference,
    )


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioInputs:
    """All domain and kernel inputs for the repository's synthetic portfolio experiment."""

    problem: PortfolioProblem
    graph_policy: PortfolioGraphPolicy
    adapter: MeanVariancePortfolioAdapter
    config: ResolvedRunConfig
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioAnalysis:
    """Notebook-facing presentation data reconstructed exclusively from saved artifacts."""

    artifacts: ExperimentRunArtifacts
    graph: ReductionGraph
    asset_ids: tuple[str, ...]
    correlation: tuple[tuple[float, ...], ...]
    correlation_threshold: float
    retained_item_ids: tuple[str, ...] | None

    @property
    def single_pass_result(self) -> Mapping[str, object]:
        """Return the persisted round, or the legacy top-level single-pass result."""
        if self.artifacts.round_results:
            return self.artifacts.round_results[0]
        return self.artifacts.result

    def node_rows(self) -> list[dict[str, object]]:
        """Return graph nodes in declared order for tables and plots."""

        return [
            {"asset": asset_id, "retention_score": self.graph.node_weights[asset_id]}
            for asset_id in self.asset_ids
        ]

    def edge_rows(self) -> list[dict[str, object]]:
        """Return graph edges with their persisted construction reasons."""

        return [
            {
                "source": left,
                "target": right,
                "reason": self.graph.edge_reasons[(left, right)],
            }
            for left, right in self.graph.edges
        ]

    def domain_rows(self) -> list[dict[str, object]]:
        """Return retained-domain membership without inferring a final portfolio selection."""

        retained = None if self.retained_item_ids is None else set(self.retained_item_ids)
        return [
            {
                "asset": asset_id,
                "retained": None if retained is None else asset_id in retained,
            }
            for asset_id in self.asset_ids
        ]


def build_synthetic_portfolio_inputs(
    run_id: str,
    *,
    asset_count: int = 30,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    mis_num_reads: int | None = None,
    mis_num_sweeps: int | None = None,
) -> SyntheticPortfolioInputs:
    """Build deterministic inputs with explicit optional solver selections.

    Args:
        run_id: Unique identifier for the run.
        asset_count: Number of assets in the synthetic portfolio. Must be >= 6.
            Default is 30 for meaningful reduction experiments.
        generation_policy: Optional generation policy. If None, uses default_generation_policy().
        graph_policy: Optional graph policy. If None, uses default_graph_policy() with near_duplicate.
        mis_solver_id: MIS solver to use.
        classical_solver_id: Classical solver to use.
        mis_num_reads: Optional D-Wave num_reads parameter.
        mis_num_sweeps: Optional D-Wave num_sweeps parameter.

    Returns:
        SyntheticPortfolioInputs with problem, adapter, and configuration.

    Raises:
        ValueError: If asset_count < 6 or if D-Wave parameters are used with
            a non-D-Wave solver.
    """
    from qreduce.experiments.portfolio_generator import (
        default_generation_policy,
        generate_portfolio_data,
    )

    if asset_count < 6:
        raise ValueError("asset_count must be at least 6 for meaningful experiments.")

    # Use provided policies or defaults
    if generation_policy is None:
        generation_policy = default_generation_policy(asset_count)
    elif generation_policy.asset_count != asset_count:
        raise ValueError(
            f"generation_policy.asset_count ({generation_policy.asset_count}) "
            f"does not match asset_count ({asset_count})."
        )

    if graph_policy is None:
        graph_policy = default_graph_policy()

    portfolio_data = generate_portfolio_data(generation_policy)
    problem = portfolio_data.to_problem()

    # Scale candidate_domain_max_items proportionally to asset_count
    # For 30 assets: max_items = 18 (60%)
    # Minimum is 3 to allow meaningful reduction
    candidate_domain_max_items = max(3, (asset_count * 3) // 5)

    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(
            max_reduction_rounds=1,
            candidate_domain_min_items=1,
            candidate_domain_max_items=candidate_domain_max_items,
            num_source_mis_candidates=1,
            min_reduction_ratio=0.1,
            target_binary_variables=3,
            max_end_to_end_runtime_seconds=60.0,
        ),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver_id,
        mis_execution=MISExecutionOptions(1, 17, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(
            classical_solver_id=classical_solver_id,
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
        run_identity=RunIdentity(run_id),
    )
    if mis_num_reads is not None or mis_num_sweeps is not None:
        if mis_solver_id != "dwave_simulated_annealing":
            raise ValueError(
                "mis_num_reads and mis_num_sweeps require "
                "mis_solver_id='dwave_simulated_annealing'."
            )
        provider_parameters: dict[str, object] = {}
        if mis_num_reads is not None:
            _require_positive_int(mis_num_reads, "mis_num_reads")
            provider_parameters["num_reads"] = mis_num_reads
        if mis_num_sweeps is not None:
            _require_positive_int(mis_num_sweeps, "mis_num_sweeps")
            provider_parameters["num_sweeps"] = mis_num_sweeps
        config = replace(
            config,
            mis_execution=replace(
                config.mis_execution,
                provider_parameters=provider_parameters,
            ),
        )
    return SyntheticPortfolioInputs(
        problem=problem,
        graph_policy=graph_policy,
        adapter=MeanVariancePortfolioAdapter(graph_policy),
        config=config,
        generation_policy=generation_policy,
    )


def run_synthetic_portfolio_experiment(
    run_id: str,
    *,
    output_root: str | Path = "outputs",
    asset_count: int = 30,
    generation_policy: "SyntheticPortfolioGenerationPolicy | None" = None,
    graph_policy: PortfolioGraphPolicy | None = None,
    mis_solver_id: str = "local_greedy",
    classical_solver_id: str = "scip",
    mis_num_reads: int | None = None,
    mis_num_sweeps: int | None = None,
    model_export_enabled: bool = False,
    model_export_path: str | None = None,
) -> ExperimentRun:
    """Run and persist the deterministic synthetic portfolio experiment.

    Args:
        run_id: Unique identifier for the run.
        output_root: Root directory for experiment artifacts.
        asset_count: Number of assets in the synthetic portfolio. Must be >= 6.
            Default is 30 for meaningful reduction experiments.
        generation_policy: Optional generation policy. If None, uses default.
        graph_policy: Optional graph policy. If None, uses near_duplicate default.
        mis_solver_id: MIS solver to use.
        classical_solver_id: Classical solver to use.
        mis_num_reads: Optional D-Wave num_reads parameter.
        mis_num_sweeps: Optional D-Wave num_sweeps parameter.
        model_export_enabled: Whether to export the residual model.
        model_export_path: Optional path for model export.

    Returns:
        ExperimentRun with the run directory and result.
    """
    inputs = build_synthetic_portfolio_inputs(
        run_id,
        asset_count=asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        mis_solver_id=mis_solver_id,
        classical_solver_id=classical_solver_id,
        mis_num_reads=mis_num_reads,
        mis_num_sweeps=mis_num_sweeps,
    )
    experiment_metadata: dict[str, object] = {
        "portfolio_graph_policy": inputs.graph_policy,
    }
    if inputs.generation_policy is not None:
        experiment_metadata["generation_policy"] = inputs.generation_policy

    return run_experiment(
        SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,
        inputs.problem,
        inputs.adapter,
        replace(inputs.config, classical_solve=replace(
            inputs.config.classical_solve,
            model_export_enabled=model_export_enabled,
            model_export_path=model_export_path,
        )),
        output_root=output_root,
        experiment_metadata=experiment_metadata,
    )


def load_synthetic_portfolio_analysis(
    run_directory: str | Path,
) -> SyntheticPortfolioAnalysis:
    """Load and validate presentation data for the synthetic portfolio experiment."""

    artifacts = load_experiment_run(run_directory)
    if artifacts.manifest["experiment_id"] != SYNTHETIC_PORTFOLIO_EXPERIMENT_ID:
        raise ExperimentArtifactError(
            "Artifact directory does not contain the synthetic portfolio experiment."
        )

    # Schema 1.1: canonical MWIS data is inside round_results
    # Schema 1.0: canonical_mwis_problem.json is a separate file
    graph_data = artifacts.canonical_mwis_problem
    if graph_data is None and artifacts.round_results:
        # Try to extract from round_results (schema 1.1)
        round_0 = artifacts.round_results[0]
        compilation = round_0.get("mis_compilation_result") or {}
        job = compilation.get("compiled_job") or {}
        graph_data = job.get("compiled_problem")

    if graph_data is None:
        raise ExperimentArtifactError(
            "Synthetic portfolio analysis requires canonical MWIS problem data."
        )
    graph = _rebuild_graph(graph_data)
    problem = _require_mapping(artifacts.problem, "problem.json")
    asset_ids = _string_tuple(problem.get("asset_ids"), "problem.asset_ids")
    covariance = _numeric_matrix(problem.get("covariance"), len(asset_ids), "problem.covariance")
    if graph.node_ids != asset_ids:
        raise ExperimentArtifactError("Persisted graph order does not match portfolio asset order.")
    policy = _require_mapping(
        artifacts.experiment_metadata.get("portfolio_graph_policy"),
        "experiment_metadata.portfolio_graph_policy",
    )
    threshold = _finite_float(
        policy.get("correlation_absolute_threshold"),
        "portfolio_graph_policy.correlation_absolute_threshold",
    )
    retained_item_ids = _retained_item_ids(artifacts.result)
    return SyntheticPortfolioAnalysis(
        artifacts=artifacts,
        graph=graph,
        asset_ids=asset_ids,
        correlation=_correlation_matrix(covariance),
        correlation_threshold=threshold,
        retained_item_ids=retained_item_ids,
    )


def _rebuild_graph(canonical_problem: Mapping[str, object]) -> ReductionGraph:
    graph_data = _require_mapping(canonical_problem.get("graph"), "canonical_mwis_problem.graph")
    node_ids = _string_tuple(graph_data.get("node_ids"), "graph.node_ids")
    node_weights_data = _require_mapping(graph_data.get("node_weights"), "graph.node_weights")
    node_weights = {
        node_id: _finite_float(node_weights_data.get(node_id), f"graph.node_weights[{node_id!r}]")
        for node_id in node_ids
    }
    edges = tuple(
        tuple(_string_tuple(edge, "graph.edges entry"))
        for edge in _require_sequence(graph_data.get("edges"), "graph.edges")
    )
    if any(len(edge) != 2 for edge in edges):
        raise ExperimentArtifactError("Each graph edge must contain exactly two node IDs.")
    edge_reasons: dict[tuple[str, str], str] = {}
    edge_reasons_data = graph_data.get("edge_reasons")
    if isinstance(edge_reasons_data, dict):
        # edge_reasons as dict (newer format from to_primitive with tuple keys as strings)
        for edge_key, reason in edge_reasons_data.items():
            # Parse edge key like "('asset-a', 'asset-b')" or just use edges
            if not isinstance(reason, str) or not reason.strip():
                raise ExperimentArtifactError("Each graph edge reason must be a non-blank string.")
        # Build edge_reasons from edges list assuming same order
        for edge in edges:
            # Try to find matching reason
            edge_key = str(edge)  # tuple string repr
            if edge_key in edge_reasons_data:
                edge_reasons[edge] = edge_reasons_data[edge_key]
            else:
                # Fallback: use edge index from edges list
                edge_reasons[edge] = "persisted edge"
    else:
        # edge_reasons as array (original format from to_dict)
        for record in _require_sequence(edge_reasons_data, "graph.edge_reasons"):
            record_data = _require_mapping(record, "graph.edge_reasons entry")
            edge_values = tuple(_string_tuple(record_data.get("edge"), "graph.edge_reasons.edge"))
            if len(edge_values) != 2:
                raise ExperimentArtifactError("Each graph edge reason must reference exactly two node IDs.")
            reason = record_data.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ExperimentArtifactError("Each graph edge reason must be a non-blank string.")
            edge_reasons[(edge_values[0], edge_values[1])] = reason
    graph_policy_id = graph_data.get("graph_policy_id")
    graph_policy_version = graph_data.get("graph_policy_version")
    if not isinstance(graph_policy_id, str) or not isinstance(graph_policy_version, str):
        raise ExperimentArtifactError("Persisted graph policy metadata is invalid.")
    return ReductionGraph(
        node_ids=node_ids,
        node_weights=node_weights,
        edges=edges,
        edge_reasons=edge_reasons,
        graph_policy_id=graph_policy_id,
        graph_policy_version=graph_policy_version,
    )


def _retained_item_ids(result: Mapping[str, object]) -> tuple[str, ...] | None:
    # Schema 1.1: final_retained_item_ids or cumulative_fixing_manifest at top level
    if "final_retained_item_ids" in result:
        return _string_tuple(result.get("final_retained_item_ids"), "run_result.final_retained_item_ids")
    # Schema 1.0: fixing_manifest and retained_item_ids at top level
    if result.get("fixing_manifest") is None:
        return None
    return _string_tuple(result.get("retained_item_ids"), "run_result.retained_item_ids")


def _correlation_matrix(
    covariance: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(value / math.sqrt(values[row] * covariance[column][column]) for column, value in enumerate(values))
        for row, values in enumerate(covariance)
    )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ExperimentArtifactError(f"{field} must be a JSON object.")
    return value


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise ExperimentArtifactError(f"{field} must be a JSON array.")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    values = _require_sequence(value, field)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ExperimentArtifactError(f"{field} must contain non-blank strings.")
    return tuple(values)  # type: ignore[return-value]


def _numeric_matrix(value: object, size: int, field: str) -> tuple[tuple[float, ...], ...]:
    rows = _require_sequence(value, field)
    if len(rows) != size:
        raise ExperimentArtifactError(f"{field} must have {size} rows.")
    matrix = tuple(tuple(_finite_float(entry, field) for entry in _require_sequence(row, field)) for row in rows)
    if any(len(row) != size for row in matrix):
        raise ExperimentArtifactError(f"{field} must be a {size} by {size} matrix.")
    if any(row[index] <= 0 for index, row in enumerate(matrix)):
        raise ExperimentArtifactError(f"{field} must have strictly positive diagonal values.")
    return matrix


def _finite_float(value: object, field: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise ExperimentArtifactError(f"{field} must be finite numeric data.")
    return float(value)


def _require_positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be an integer greater than zero.")


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic portfolio QReduce experiment.")
    parser.add_argument("--run-id", required=True, help="Unique run identifier used under the experiment output directory.")
    parser.add_argument("--output-root", default="outputs", help="Root directory for repository experiment artifacts.")
    parser.add_argument("--model-export", action="store_true", help="Export the residual model.")
    parser.add_argument("--model-export-path", help="Optional .lp or .mps export file path.")
    parser.add_argument(
        "--mis-solver-id",
        choices=("local_greedy", "dwave_simulated_annealing"),
        default="local_greedy",
        help="Built-in MIS solver ID.",
    )
    parser.add_argument(
        "--classical-solver-id",
        choices=("cplex", "scip"),
        default="scip",
        help="Built-in residual classical solver ID.",
    )
    parser.add_argument(
        "--mis-num-reads",
        type=int,
        help="Optional D-Wave simulated-annealing num_reads parameter.",
    )
    parser.add_argument(
        "--mis-num-sweeps",
        type=int,
        help="Optional D-Wave simulated-annealing num_sweeps parameter.",
    )
    parser.add_argument(
        "--asset-count",
        type=int,
        default=30,
        help="Number of assets in the synthetic portfolio. Must be >= 6. Default: 30.",
    )
    # Graph edge mode options
    parser.add_argument(
        "--graph-edge-mode",
        choices=("correlation_only", "near_duplicate"),
        default="near_duplicate",
        help="Graph edge semantics: correlation_only or near_duplicate. Default: near_duplicate.",
    )
    parser.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.90,
        help="Absolute correlation threshold for edges. Default: 0.90.",
    )
    parser.add_argument(
        "--near-duplicate-max-relative-return-difference",
        type=float,
        default=0.10,
        help="Max relative return difference for near_duplicate edges. Default: 0.10.",
    )
    parser.add_argument(
        "--near-duplicate-max-relative-variance-difference",
        type=float,
        default=0.10,
        help="Max relative variance difference for near_duplicate edges. Default: 0.10.",
    )
    # Generation policy options
    parser.add_argument(
        "--generation-seed",
        type=int,
        default=42,
        help="Random seed for generation policy. Default: 42.",
    )
    parser.add_argument(
        "--observation-count",
        type=int,
        help="Number of historical observations. Default: 10 * asset_count.",
    )
    arguments = parser.parse_args()
    if arguments.model_export_path and not arguments.model_export:
        parser.error("--model-export-path requires --model-export")
    if arguments.asset_count < 6:
        parser.error("--asset-count must be at least 6")

    # Build generation policy
    from qreduce.experiments.portfolio_generator import default_generation_policy
    generation_policy = default_generation_policy(
        arguments.asset_count,
        random_seed=arguments.generation_seed,
        observation_count=arguments.observation_count,
    )

    # Build graph policy
    graph_policy = default_graph_policy(
        edge_mode=arguments.graph_edge_mode,
        correlation_threshold=arguments.correlation_threshold,
        near_duplicate_max_relative_return_difference=arguments.near_duplicate_max_relative_return_difference,
        near_duplicate_max_relative_variance_difference=arguments.near_duplicate_max_relative_variance_difference,
    )

    run = run_synthetic_portfolio_experiment(
        arguments.run_id,
        output_root=arguments.output_root,
        asset_count=arguments.asset_count,
        generation_policy=generation_policy,
        graph_policy=graph_policy,
        mis_solver_id=arguments.mis_solver_id,
        classical_solver_id=arguments.classical_solver_id,
        mis_num_reads=arguments.mis_num_reads,
        mis_num_sweeps=arguments.mis_num_sweeps,
        model_export_enabled=arguments.model_export,
        model_export_path=arguments.model_export_path,
    )
    print(run.run_directory)


if __name__ == "__main__":
    _main()