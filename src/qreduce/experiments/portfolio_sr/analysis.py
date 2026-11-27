"""Analysis utilities for Sharpe portfolio experiments.

This module provides:
- Loading and parsing experiment artifacts
- Extracting key metrics and summaries
- Comparing baseline vs reduced results
- Generating analysis data for notebooks
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qreduce.experiments.artifacts import ExperimentRunArtifacts, load_experiment_run

if TYPE_CHECKING:
    from qreduce.experiments.portfolio_sr.benchmark import BenchmarkResult


@dataclass(frozen=True, slots=True)
class SolutionMetrics:
    """Key metrics extracted from a solution."""

    sharpe_ratio: float | None
    expected_return: float | None
    volatility: float | None
    position_count: int | None
    max_weight: float | None
    objective_value: float | None
    selected_count: int | None = None


@dataclass(frozen=True, slots=True)
class ReductionMetrics:
    """Metrics related to domain reduction."""

    original_ticker_count: int
    retained_ticker_count: int
    excluded_ticker_count: int
    reduction_ratio: float
    graph_node_count: int | None
    graph_edge_count: int | None


@dataclass(frozen=True, slots=True)
class TimingMetrics:
    """Timing information from experiment run."""

    total_runtime_seconds: float | None
    graph_build_time_seconds: float | None
    mis_execution_time_seconds: float | None
    classical_solve_time_seconds: float | None


@dataclass(frozen=True, slots=True)
class SharpePortfolioAnalysis:
    """Complete analysis of a Sharpe portfolio experiment run."""

    run_id: str
    run_directory: Path
    run_status: str
    is_success: bool
    is_classical_only: bool
    reduction_round_count: int

    # Problem info
    problem_summary: dict[str, Any]

    # Metrics
    solution: SolutionMetrics | None
    reduction: ReductionMetrics | None
    timing: TimingMetrics | None

    # Raw data for detailed analysis
    artifacts: ExperimentRunArtifacts

    @property
    def sharpe_ratio(self) -> float | None:
        """Convenience accessor for Sharpe ratio."""
        return self.solution.sharpe_ratio if self.solution else None

    @property
    def position_count(self) -> int | None:
        """Convenience accessor for position count."""
        return self.solution.position_count if self.solution else None


def load_sharpe_portfolio_analysis(
    run_directory: str | Path,
) -> SharpePortfolioAnalysis:
    """Load and analyze a Sharpe portfolio experiment run.

    Args:
        run_directory: Path to the run directory.

    Returns:
        SharpePortfolioAnalysis with extracted metrics.

    Raises:
        ExperimentArtifactError: If artifacts are invalid.
    """
    artifacts = load_experiment_run(run_directory)

    # Extract run status from run_result
    result = artifacts.result
    run_result = result.get("run_result", {})
    if isinstance(run_result, dict):
        run_status = str(run_result.get("run_status", "unknown"))
    else:
        run_status = "unknown"

    is_success = run_status in ("success", "partial_success")

    # Extract problem summary
    problem = artifacts.problem
    problem_summary = _extract_problem_summary(problem) if isinstance(problem, dict) else {}

    # Extract solution metrics from domain_evaluation_metrics and postcheck
    solution = _extract_solution_metrics(result) if _solution_weights(artifacts) else None

    # Extract reduction metrics
    # Include for QReduce (not classical_only) OR for screenings (has fixing manifest with exclusions)
    has_screening_fixing = _has_fixing_exclusions(artifacts)
    reduction = _extract_reduction_metrics(artifacts, problem_summary) if (not artifacts.is_classical_only or has_screening_fixing) else None

    # Extract timing metrics
    timing = _extract_timing_metrics(result)

    # Get run_id from config
    config = artifacts.config
    run_identity = config.get("run_identity", {})
    if isinstance(run_identity, dict):
        run_id = str(run_identity.get("run_id", "unknown"))
    else:
        run_id = str(artifacts.manifest.get("run_id", "unknown"))

    return SharpePortfolioAnalysis(
        run_id=run_id,
        run_directory=artifacts.run_directory,
        run_status=run_status,
        is_success=is_success,
        is_classical_only=artifacts.is_classical_only,
        reduction_round_count=artifacts.reduction_round_count,
        problem_summary=problem_summary,
        solution=solution,
        reduction=reduction,
        timing=timing,
        artifacts=artifacts,
    )


def _extract_problem_summary(problem: dict[str, Any]) -> dict[str, Any]:
    """Extract problem summary from artifact data.

    Handles both SharpePortfolioProblem and TransformedSharpeProblem.
    For transformed problems, extracts data from original_problem.
    """
    # If this is a TransformedSharpeProblem, get the original
    base_problem = _original_problem_data(problem)
    if base_problem is not problem:
        retained_tickers = problem.get("retained_tickers", [])
        fixing_manifest = problem.get("fixing_manifest", {})
        excluded = fixing_manifest.get("excluded_item_ids", []) if isinstance(fixing_manifest, dict) else []
    else:
        # SharpePortfolioProblem - use directly
        retained_tickers = problem.get("tickers", [])
        excluded = []

    original_tickers = base_problem.get("tickers", [])

    return {
        "tickers": original_tickers,
        "ticker_count": base_problem.get("ticker_count", len(original_tickers)),
        "sector_count": base_problem.get("sector_count", len(set(base_problem.get("sectors", {}).values()))),
        "max_positions": base_problem.get("max_positions"),
        "min_selected_assets": base_problem.get("min_selected_assets"),
        "lower_bound": base_problem.get("lower_bound", 0.0),
        "lower_bounds": base_problem.get("lower_bounds"),
        "has_sector_constraints": base_problem.get("sector_constraints") is not None,
        "mu_range": base_problem.get("mu_range"),
        "x_scale_bounds": base_problem.get("x_scale_bounds"),
        # Additional fields for screening context
        "original_ticker_count": len(original_tickers),
        "retained_ticker_count": len(retained_tickers),
        "excluded_ticker_count": len(excluded),
        "is_transformed": base_problem is not problem,
    }


def _original_problem_data(problem: Mapping[str, Any]) -> Mapping[str, Any]:
    """Unwrap the financial problem shared by baseline and screening artifacts."""
    original = problem.get("original_problem")
    return original if isinstance(original, Mapping) else problem


def _has_adopted_solution(result: Mapping[str, Any]) -> bool:
    """Require an adopted, post-checked solution for financial presentation."""
    run = result.get("run_result")
    postcheck = result.get("postcheck_result")
    return (
        isinstance(run, Mapping)
        and run.get("run_status") in ("success", "partial_success")
        and run.get("adoption_status") == "adopted"
        and isinstance(postcheck, Mapping)
        and postcheck.get("postcheck_feasible") is True
    )


def _extract_solution_metrics(result: Mapping[str, Any]) -> SolutionMetrics | None:
    """Extract solution metrics from result artifact.

    Uses domain_evaluation_metrics with metric_id field.
    """
    # First try domain_evaluation_metrics (preferred)
    domain_metrics = result.get("domain_evaluation_metrics")
    if isinstance(domain_metrics, (list, tuple)) and domain_metrics:
        # domain_evaluation_metrics is a list of DomainEvaluationMetric
        # Field is metric_id, not name
        metrics_dict: dict[str, float | None] = {}
        for metric in domain_metrics:
            if isinstance(metric, dict):
                metric_id = metric.get("metric_id")
                value = metric.get("value")
                if metric_id:
                    metrics_dict[metric_id] = _safe_float(value)

        return SolutionMetrics(
            sharpe_ratio=metrics_dict.get("sharpe_ratio"),
            expected_return=metrics_dict.get("expected_return"),
            volatility=metrics_dict.get("volatility"),
            position_count=_safe_int(metrics_dict.get("position_count")),
            max_weight=metrics_dict.get("max_weight"),
            objective_value=metrics_dict.get("objective_value"),
            selected_count=_safe_int(metrics_dict.get("selected_count")),
        )

    # Fall back to postcheck_result tolerances_used (has some metrics)
    postcheck = result.get("postcheck_result")
    if isinstance(postcheck, dict):
        tolerances = postcheck.get("tolerances_used", {})
        if isinstance(tolerances, dict):
            return SolutionMetrics(
                sharpe_ratio=_safe_float(tolerances.get("sharpe_ratio")),
                expected_return=None,
                volatility=None,
                position_count=_safe_int(tolerances.get("position_count")),
                max_weight=None,
                objective_value=_safe_float(tolerances.get("objective_recomputed") or postcheck.get("objective_recomputed")),
                selected_count=_safe_int(tolerances.get("selected_count")),
            )

    return None


def _has_fixing_exclusions(artifacts: ExperimentRunArtifacts) -> bool:
    """Check if artifacts have fixing manifest with exclusions (screening scenario)."""
    fixing_data = artifacts.fixing_manifest
    if fixing_data is None:
        result = artifacts.result
        fixing_data = result.get("cumulative_fixing_manifest")

    if fixing_data is None or not isinstance(fixing_data, dict):
        return False

    excluded = fixing_data.get("excluded_item_ids", [])
    return isinstance(excluded, (list, tuple)) and len(excluded) > 0


def _extract_reduction_metrics(
    artifacts: ExperimentRunArtifacts,
    problem_summary: dict[str, Any] | None = None,
) -> ReductionMetrics | None:
    """Extract reduction metrics from artifacts.

    Uses fixing manifest for exclusion counts, and problem_summary for
    original ticker count when available (handles screening scenarios).
    """
    # Use fixing_manifest from manifest or cumulative_fixing_manifest from result
    fixing_data = artifacts.fixing_manifest
    if fixing_data is None:
        # Try from result
        result = artifacts.result
        fixing_data = result.get("cumulative_fixing_manifest")

    if fixing_data is None or not isinstance(fixing_data, dict):
        return None

    retained = fixing_data.get("retained_item_ids", [])
    excluded = fixing_data.get("excluded_item_ids", [])

    if not isinstance(retained, (list, tuple)):
        retained = []
    if not isinstance(excluded, (list, tuple)):
        excluded = []

    # For original count, prefer problem_summary.original_ticker_count if available
    # (handles TransformedSharpeProblem correctly)
    if problem_summary and "original_ticker_count" in problem_summary:
        original_count = problem_summary["original_ticker_count"]
    else:
        original_count = len(retained) + len(excluded)

    retained_count = len(retained)
    excluded_count = len(excluded)
    reduction_ratio = excluded_count / original_count if original_count > 0 else 0.0

    # Try to extract graph info from round results
    graph_nodes = None
    graph_edges = None

    if artifacts.round_results:
        first_round = artifacts.round_results[0]
        if isinstance(first_round, dict):
            graph_data = first_round.get("graph")
            if isinstance(graph_data, dict):
                graph_nodes = _safe_int(graph_data.get("node_count"))
                graph_edges = _safe_int(graph_data.get("edge_count"))

    return ReductionMetrics(
        original_ticker_count=original_count,
        retained_ticker_count=retained_count,
        excluded_ticker_count=excluded_count,
        reduction_ratio=reduction_ratio,
        graph_node_count=graph_nodes,
        graph_edge_count=graph_edges,
    )


def _extract_timing_metrics(result: Mapping[str, Any]) -> TimingMetrics | None:
    """Extract timing metrics from result artifact."""
    # Primary: metrics.end_to_end_runtime_seconds
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        total_time = _safe_float(metrics.get("end_to_end_runtime_seconds"))
        if total_time is not None:
            return TimingMetrics(
                total_runtime_seconds=total_time,
                graph_build_time_seconds=None,  # Not exposed in metrics
                mis_execution_time_seconds=None,
                classical_solve_time_seconds=None,
            )

    # Fallback: run_result.elapsed_seconds (if available)
    run_result = result.get("run_result")
    if isinstance(run_result, dict):
        elapsed = _safe_float(run_result.get("elapsed_seconds"))
        if elapsed is not None:
            return TimingMetrics(
                total_runtime_seconds=elapsed,
                graph_build_time_seconds=None,
                mis_execution_time_seconds=None,
                classical_solve_time_seconds=None,
            )

    return None


def _safe_float(value: Any) -> float | None:
    """Safely convert to float, returning None if not possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    """Safely convert to int, returning None if not possible."""
    if value is None:
        return None
    try:
        i = int(float(value))  # Handle float-like strings
        return i
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class ComparisonSummary:
    """Summary comparing multiple experiment runs."""

    runs: tuple[SharpePortfolioAnalysis, ...]

    @property
    def best_sharpe(self) -> SharpePortfolioAnalysis | None:
        """Return run with highest Sharpe ratio."""
        valid = [r for r in self.runs if r.is_success and r.solution is not None and r.sharpe_ratio is not None]
        if not valid:
            return None
        return max(valid, key=lambda r: r.sharpe_ratio or 0)

    @property
    def fastest(self) -> SharpePortfolioAnalysis | None:
        """Return run with lowest total time."""
        valid = [
            r for r in self.runs
            if r.is_success and r.solution is not None
            and r.timing and r.timing.total_runtime_seconds is not None
            and math.isfinite(r.timing.total_runtime_seconds)
            and r.timing.total_runtime_seconds >= 0
        ]
        if not valid:
            return None
        return min(valid, key=lambda r: r.timing.total_runtime_seconds)

    def to_dataframe_rows(self) -> list[dict[str, Any]]:
        """Convert to list of dicts for DataFrame construction."""
        rows = []
        for run in self.runs:
            row: dict[str, Any] = {
                "run_id": run.run_id,
                "status": run.run_status,
                "is_classical_only": run.is_classical_only,
                "ticker_count": run.problem_summary.get("ticker_count"),
            }

            if run.solution:
                row.update({
                    "sharpe_ratio": run.solution.sharpe_ratio,
                    "expected_return": run.solution.expected_return,
                    "volatility": run.solution.volatility,
                    "position_count": run.solution.position_count,
                    "selected_count": run.solution.selected_count,
                    "max_weight": run.solution.max_weight,
                })

            if run.reduction:
                row.update({
                    "retained_count": run.reduction.retained_ticker_count,
                    "reduction_ratio": run.reduction.reduction_ratio,
                })

            if run.timing:
                row["total_time"] = run.timing.total_runtime_seconds

            rows.append(row)

        return rows


def compare_runs(
    run_directories: Sequence[str | Path],
) -> ComparisonSummary:
    """Load and compare multiple experiment runs.

    Args:
        run_directories: Paths to run directories to compare.

    Returns:
        ComparisonSummary with all loaded runs.
    """
    analyses = tuple(
        load_sharpe_portfolio_analysis(d)
        for d in run_directories
    )
    return ComparisonSummary(runs=analyses)


def _solution_weights(artifacts: ExperimentRunArtifacts) -> dict[str, float]:
    """Reconstruct a complete adopted solution, or return unavailable data."""
    if not _has_adopted_solution(artifacts.result):
        return {}
    if not isinstance(artifacts.problem, Mapping):
        return {}
    problem = _original_problem_data(artifacts.problem)
    tickers = problem.get("tickers")
    if not isinstance(tickers, (list, tuple)) or not tickers:
        return {}
    classical = artifacts.result.get("classical_result")
    values = classical.get("variable_values") if isinstance(classical, Mapping) else None
    if not isinstance(values, Mapping):
        return {}
    scale = _safe_float(values.get("x_scale"))
    if scale is None or scale <= 0:
        return {}
    weights: dict[str, float] = {}
    for ticker in tickers:
        value = _safe_float(values.get(f"x_scaled__{ticker}"))
        if value is None:
            return {}
        weight = value / scale
        if not math.isfinite(weight):
            return {}
        weights[ticker] = weight
    return weights


def extract_sector_exposures(
    artifacts: ExperimentRunArtifacts,
) -> dict[str, float]:
    """Aggregate complete adopted weights using the original sector metadata.

    Failed or incomplete solutions return an empty mapping, not a partial
    distribution. Zero-weight sectors remain visible. No weights are corrected.
    """
    weights = _solution_weights(artifacts)
    if not weights or not isinstance(artifacts.problem, Mapping):
        return {}
    sectors = _original_problem_data(artifacts.problem).get("sectors")
    if not isinstance(sectors, Mapping):
        return {}
    exposures: dict[str, float] = {}
    for ticker, weight in weights.items():
        sector = sectors.get(ticker)
        if not isinstance(sector, str) or not sector:
            return {}
        exposures[sector] = exposures.get(sector, 0.0) + weight
    return exposures


def extract_portfolio_weights(
    artifacts: ExperimentRunArtifacts,
    *,
    weight_tolerance: float = 1e-9,
) -> dict[str, float]:
    """Return adopted weights above a finite non-negative display threshold.

    Pass zero to retain zero-weight excluded assets for constraint checks.
    Filtering is for presentation only: weights are never renormalized.
    """
    if not math.isfinite(weight_tolerance) or weight_tolerance < 0:
        raise ValueError("weight_tolerance must be finite and non-negative.")
    return {
        ticker: weight
        for ticker, weight in _solution_weights(artifacts).items()
        if weight >= weight_tolerance
    }


def summarize_benchmark_results(
    results: Sequence[BenchmarkResult],
) -> dict[str, Any]:
    """Summarize a list of benchmark results.

    Args:
        results: List of BenchmarkResult from benchmark runs.

    Returns:
        Dictionary with summary statistics.
    """
    summaries = []

    for r in results:
        summary: dict[str, Any] = {
            "method": r.method,
            "run_id": r.run_id,
            "is_success": r.is_success,
            "sharpe_ratio": r.sharpe_ratio,
            "retained_count": r.retained_ticker_count,
            "prep_time": r.preparation_time_seconds,
            "total_time": r.total_time_seconds,
        }
        summaries.append(summary)

    # Find best Sharpe among successful runs
    successful = [s for s in summaries if s["is_success"] and s["sharpe_ratio"] is not None]
    best_sharpe = max((s["sharpe_ratio"] for s in successful), default=None)

    # Compute baseline reference (first successful method)
    baseline = next((s for s in summaries if s["method"] == "full_baseline" and s["is_success"]), None)

    return {
        "runs": summaries,
        "best_sharpe": best_sharpe,
        "baseline_sharpe": baseline["sharpe_ratio"] if baseline else None,
        "successful_count": len(successful),
        "total_count": len(summaries),
    }
