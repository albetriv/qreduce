"""Benchmark comparisons for Sharpe portfolio experiment.

This module provides baseline comparison methods:
1. Full problem without reduction (classical-only)
2. QReduce with MIS reduction
3. Simple screening by individual Sharpe ratio
4. Random screening (with multiple seeds)
5. Correlation-based screening

Each method uses the same input data, constraints, and solver for fair comparison.
All screening methods use the same original problem with fixing manifests for
excluded tickers, ensuring fair comparison with QReduce.
"""

import logging
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from qreduce.domains.contracts import FixingEntry, FixingManifest
from qreduce.experiments.portfolio_sr.execution import (
    EXPERIMENT_ID,
    _build_classical_solve_options,
    _build_mis_execution_options,
    _build_resolved_run_config,
    run_sharpe_portfolio_from_inputs,
)
from qreduce.experiments.portfolio_sr.formulation import compute_retention_scores
from qreduce.experiments.portfolio_sr.inputs import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SP500_CSV,
    SharpePortfolioInputs,
    build_sharpe_portfolio_inputs,
    default_reduction_policy,
)
from qreduce.experiments.portfolio_sr.models import (
    SectorConstraints,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.experiments.runner import ExperimentRun, run_experiment
from qreduce.solving.mwis import builtin_mis_solver_registry
from qreduce.solving.residual import builtin_classical_solver_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Result of a single benchmark run."""

    method: str
    run_id: str
    run: ExperimentRun
    preparation_time_seconds: float
    total_time_seconds: float
    retained_ticker_count: int | None

    @property
    def sharpe_ratio(self) -> float | None:
        """Extract Sharpe ratio from domain_evaluation_metrics."""
        metrics = self.run.result.domain_evaluation_metrics
        if metrics:
            for metric in metrics:
                if metric.metric_id == "sharpe_ratio":
                    return metric.value
        return None

    @property
    def is_success(self) -> bool:
        """Whether the run completed successfully."""
        return self.run.result.run_result.run_status.value in ("success", "partial_success")


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark suite."""

    # Data configuration
    csv_path: str | Path = DEFAULT_SP500_CSV
    asset_count: int | None = 50
    start_date: date | None = None
    end_date: date | None = None
    return_convention: str = "log"

    # Problem configuration
    upper_bound: float = 1.0
    lower_bound: float = field(default=0.0, kw_only=True)
    sector_constraints: SectorConstraints | None = None
    max_positions: int | None = None
    min_selected_assets: int | None = field(default=None, kw_only=True)
    lower_bounds: Mapping[str, float] | None = field(default=None, kw_only=True)

    # Solver configuration
    classical_solver_id: str = "scip"
    classical_time_limit_seconds: float = 60.0

    # Benchmark configuration
    random_seeds: Sequence[int] = (42, 123, 456)
    target_retention_fraction: float = 0.5

    # Output
    output_root: str | Path = DEFAULT_OUTPUT_ROOT


def run_benchmark_suite(
    run_id_prefix: str,
    config: BenchmarkConfig,
    *,
    skip_full: bool = False,
    skip_qreduce: bool = False,
    skip_sharpe_screening: bool = False,
    skip_random_screening: bool = False,
    skip_correlation_screening: bool = False,
) -> list[BenchmarkResult]:
    """Run complete benchmark suite.

    Args:
        run_id_prefix: Prefix for run IDs.
        config: Benchmark configuration.
        skip_full: Skip full problem (no reduction).
        skip_qreduce: Skip QReduce reduction.
        skip_sharpe_screening: Skip Sharpe-based screening.
        skip_random_screening: Skip random screening.
        skip_correlation_screening: Skip correlation screening.

    Returns:
        List of BenchmarkResult for each method.
    """
    results: list[BenchmarkResult] = []

    # Build shared inputs
    logger.info("Building shared inputs for benchmark suite")
    inputs = build_sharpe_portfolio_inputs(
        csv_path=config.csv_path,
        asset_count=config.asset_count,
        start_date=config.start_date,
        end_date=config.end_date,
        return_convention=config.return_convention,
        upper_bound=config.upper_bound,
        lower_bound=config.lower_bound,
        sector_constraints=config.sector_constraints,
        max_positions=config.max_positions,
        min_selected_assets=config.min_selected_assets,
        lower_bounds=config.lower_bounds,
    )

    target_count = max(
        1,
        inputs.problem.min_selected_assets or 0,
        int(inputs.problem.ticker_count * config.target_retention_fraction),
    )

    # 1. Full problem (classical-only baseline)
    if not skip_full:
        logger.info("Running full problem baseline")
        result = run_full_baseline(
            f"{run_id_prefix}_full",
            inputs,
            classical_solver_id=config.classical_solver_id,
            classical_time_limit_seconds=config.classical_time_limit_seconds,
            output_root=config.output_root,
        )
        results.append(result)

    # 2. QReduce reduction
    if not skip_qreduce:
        logger.info("Running QReduce reduction")
        result = run_qreduce_reduction(
            f"{run_id_prefix}_qreduce",
            inputs,
            target_retention_count=target_count,
            classical_solver_id=config.classical_solver_id,
            classical_time_limit_seconds=config.classical_time_limit_seconds,
            output_root=config.output_root,
        )
        results.append(result)

    # 3. Sharpe-based screening
    if not skip_sharpe_screening:
        logger.info("Running Sharpe-based screening")
        result = run_sharpe_screening(
            f"{run_id_prefix}_sharpe",
            inputs,
            target_count=target_count,
            classical_solver_id=config.classical_solver_id,
            classical_time_limit_seconds=config.classical_time_limit_seconds,
            output_root=config.output_root,
        )
        results.append(result)

    # 4. Random screening (multiple seeds)
    if not skip_random_screening:
        for seed in config.random_seeds:
            logger.info("Running random screening with seed=%d", seed)
            result = run_random_screening(
                f"{run_id_prefix}_random_{seed}",
                inputs,
                target_count=target_count,
                seed=seed,
                classical_solver_id=config.classical_solver_id,
                classical_time_limit_seconds=config.classical_time_limit_seconds,
                output_root=config.output_root,
            )
            results.append(result)

    # 5. Correlation-based screening
    if not skip_correlation_screening:
        logger.info("Running correlation-based screening")
        result = run_correlation_screening(
            f"{run_id_prefix}_correlation",
            inputs,
            target_count=target_count,
            classical_solver_id=config.classical_solver_id,
            classical_time_limit_seconds=config.classical_time_limit_seconds,
            output_root=config.output_root,
        )
        results.append(result)

    return results


def run_full_baseline(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> BenchmarkResult:
    """Run full problem without reduction (classical-only).

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        BenchmarkResult for full baseline.
    """
    start = time.perf_counter()

    # Use max_reduction_rounds=0 for classical-only
    policy = replace(
        default_reduction_policy(
            inputs.problem.ticker_count,
            has_cardinality=inputs.problem.has_selection_binaries,
            min_selected_assets=inputs.problem.min_selected_assets,
        ),
        max_reduction_rounds=0,
    )

    prep_time = time.perf_counter() - start

    run = run_sharpe_portfolio_from_inputs(
        run_id,
        inputs,
        reduction_policy=policy,
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        output_root=output_root,
    )

    total_time = time.perf_counter() - start

    return BenchmarkResult(
        method="full_baseline",
        run_id=run_id,
        run=run,
        preparation_time_seconds=prep_time,
        total_time_seconds=total_time,
        retained_ticker_count=inputs.problem.ticker_count,
    )


def run_qreduce_reduction(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    target_retention_count: int | None = None,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> BenchmarkResult:
    """Run with QReduce MWIS reduction.

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs.
        target_retention_count: Target number of retained tickers.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        BenchmarkResult for QReduce.
    """
    start = time.perf_counter()

    n = inputs.problem.ticker_count
    target = target_retention_count if target_retention_count is not None else max(
        1, inputs.problem.min_selected_assets or 0, int(n * 0.6),
    )

    policy = replace(
        default_reduction_policy(
            n,
            has_cardinality=inputs.problem.has_selection_binaries,
            min_selected_assets=inputs.problem.min_selected_assets,
        ),
        max_reduction_rounds=1,
        candidate_domain_max_items=target,
    )

    prep_time = time.perf_counter() - start

    run = run_sharpe_portfolio_from_inputs(
        run_id,
        inputs,
        reduction_policy=policy,
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        output_root=output_root,
    )

    total_time = time.perf_counter() - start

    # Extract retained count from result
    manifest = run.result.cumulative_fixing_manifest
    retained = len(manifest.retained_item_ids) if manifest else n

    return BenchmarkResult(
        method="qreduce",
        run_id=run_id,
        run=run,
        preparation_time_seconds=prep_time,
        total_time_seconds=total_time,
        retained_ticker_count=retained,
    )


def run_sharpe_screening(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    target_count: int,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> BenchmarkResult:
    """Run with screening by individual Sharpe ratio.

    Selects the top-K tickers by individual Sharpe ratio (mu_i/sigma_i).
    Uses fixing on the original problem for fair comparison.

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs.
        target_count: Number of tickers to retain.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        BenchmarkResult for Sharpe screening.
    """
    start = time.perf_counter()

    # Compute Sharpe scores and select top-K
    scores = compute_retention_scores(inputs.problem, score_type="individual_sharpe")
    sorted_tickers = sorted(scores.keys(), key=lambda t: -scores[t])
    selected = sorted_tickers[:target_count]

    prep_time = time.perf_counter() - start

    # Run with fixing on original problem
    run = _run_screening_with_fixing(
        run_id,
        inputs,
        selected,
        method_name="sharpe",
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        output_root=output_root,
    )

    total_time = time.perf_counter() - start

    return BenchmarkResult(
        method="sharpe_screening",
        run_id=run_id,
        run=run,
        preparation_time_seconds=prep_time,
        total_time_seconds=total_time,
        retained_ticker_count=len(selected),
    )


def run_random_screening(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    target_count: int,
    seed: int,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> BenchmarkResult:
    """Run with random screening.

    Randomly selects K tickers with given seed for reproducibility.
    Uses fixing on the original problem for fair comparison.

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs.
        target_count: Number of tickers to retain.
        seed: Random seed for reproducibility.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        BenchmarkResult for random screening.
    """
    start = time.perf_counter()

    # Random selection
    rng = random.Random(seed)
    tickers = list(inputs.problem.tickers)
    rng.shuffle(tickers)
    selected = tickers[:target_count]

    prep_time = time.perf_counter() - start

    # Run with fixing on original problem
    run = _run_screening_with_fixing(
        run_id,
        inputs,
        selected,
        method_name=f"random_seed_{seed}",
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        output_root=output_root,
    )

    total_time = time.perf_counter() - start

    return BenchmarkResult(
        method=f"random_screening_seed_{seed}",
        run_id=run_id,
        run=run,
        preparation_time_seconds=prep_time,
        total_time_seconds=total_time,
        retained_ticker_count=len(selected),
    )


def run_correlation_screening(
    run_id: str,
    inputs: SharpePortfolioInputs,
    *,
    target_count: int,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> BenchmarkResult:
    """Run with correlation-based screening.

    Uses a simple greedy approach: start with highest Sharpe ticker,
    then iteratively add the ticker with lowest max correlation to
    already-selected tickers. Uses deterministic tie-breaking by ticker name.
    Uses fixing on the original problem for fair comparison.

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs.
        target_count: Number of tickers to retain.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        BenchmarkResult for correlation screening.
    """
    start = time.perf_counter()

    problem = inputs.problem
    scores = compute_retention_scores(problem, score_type="individual_sharpe")

    # Start with highest Sharpe ticker (sorted gives deterministic tie-break)
    sorted_by_sharpe = sorted(problem.tickers, key=lambda t: (-scores[t], t))
    selected: list[str] = [sorted_by_sharpe[0]]
    remaining = set(problem.tickers) - {selected[0]}

    # Greedily add tickers that minimize max correlation
    # Use sorted iteration for deterministic tie-breaking
    while len(selected) < target_count and remaining:
        best_ticker = None
        best_max_corr = float("inf")

        # Sort remaining tickers for deterministic iteration order
        for ticker in sorted(remaining):
            max_corr = max(
                abs(problem.correlation(ticker, s))
                for s in selected
            )
            # Strictly less-than gives deterministic selection (first alphabetically on tie)
            if max_corr < best_max_corr:
                best_max_corr = max_corr
                best_ticker = ticker

        if best_ticker is not None:
            selected.append(best_ticker)
            remaining.remove(best_ticker)
        else:
            break

    prep_time = time.perf_counter() - start

    # Run with fixing on original problem
    run = _run_screening_with_fixing(
        run_id,
        inputs,
        selected,
        method_name="correlation",
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
        output_root=output_root,
    )

    total_time = time.perf_counter() - start

    return BenchmarkResult(
        method="correlation_screening",
        run_id=run_id,
        run=run,
        preparation_time_seconds=prep_time,
        total_time_seconds=total_time,
        retained_ticker_count=len(selected),
    )


def _run_screening_with_fixing(
    run_id: str,
    inputs: SharpePortfolioInputs,
    selected_tickers: Sequence[str],
    *,
    method_name: str,
    classical_solver_id: str = "scip",
    classical_time_limit_seconds: float = 60.0,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> ExperimentRun:
    """Run screening using fixing on original problem.

    Instead of building a new problem with fewer tickers, this function:
    1. Creates a FixingManifest that fixes excluded tickers to zero
    2. Creates a TransformedSharpeProblem with the fixing
    3. Runs classical solve on the transformed problem

    This ensures all screening methods solve the same original problem
    with different fixing choices, making results directly comparable.

    Args:
        run_id: Unique run identifier.
        inputs: Pre-built inputs with original problem.
        selected_tickers: Tickers to retain (not fixed to zero).
        method_name: Name of screening method for metadata.
        classical_solver_id: Classical solver ID.
        classical_time_limit_seconds: Time limit per solve.
        output_root: Output directory.

    Returns:
        ExperimentRun with result and artifact directory.
    """
    problem = inputs.problem
    selected = tuple(selected_tickers)
    retained_set = set(selected)

    # Build variable mapping for fixing
    mapping = SharpeVariableMapping.for_problem(problem)

    # Build fixing entries for excluded tickers
    excluded = tuple(t for t in problem.tickers if t not in retained_set)
    entries: list[FixingEntry] = []

    for ticker in excluded:
        var_values: dict[str, float] = {
            mapping.x_scaled_by_ticker[ticker]: 0.0,
        }
        if mapping.delta_by_ticker is not None:
            var_values[mapping.delta_by_ticker[ticker]] = 0.0

        entries.append(FixingEntry(
            item_id=ticker,
            variable_values=var_values,
            reason=f"screening:{method_name}",
            fixing_origin="user_mandated",
            guarantee_level="user_imposed",
        ))

    # Build fixing manifest
    fixing_manifest = FixingManifest(
        retained_item_ids=selected,
        excluded_item_ids=excluded,
        entries=tuple(entries),
        origin=f"screening:{method_name}",
        round_index=0,
        provenance={"screening_method": method_name},
    )

    # Build transformed problem with fixing
    transformed = TransformedSharpeProblem(
        original_problem=problem,
        retained_tickers=selected,
        fixing_manifest=fixing_manifest,
        variable_mapping=mapping,
    )

    # Build config for classical-only run
    policy = replace(
        default_reduction_policy(
            problem.ticker_count,
            has_cardinality=problem.has_selection_binaries,
            min_selected_assets=problem.min_selected_assets,
        ),
        max_reduction_rounds=0,
    )

    mis_execution = _build_mis_execution_options(mis_solver_id="local_greedy")
    classical_solve = _build_classical_solve_options(
        classical_solver_id=classical_solver_id,
        classical_time_limit_seconds=classical_time_limit_seconds,
    )

    config = _build_resolved_run_config(
        run_id,
        reduction_policy=policy,
        mis_solver_id="local_greedy",
        mis_execution=mis_execution,
        classical_solve=classical_solve,
        policy_source=f"sharpe_portfolio_screening:{method_name}",
    )

    # Build metadata
    metadata: dict[str, object] = {
        "experiment_type": EXPERIMENT_ID,
        "source_dataset": inputs.source_dataset.to_dict(),
        "return_statistics": inputs.return_statistics.to_dict(),
        "graph_policy": inputs.graph_policy.to_dict(),
        "screening_method": method_name,
        "retained_ticker_count": len(selected),
        "excluded_ticker_count": len(excluded),
    }

    # Run experiment with transformed problem
    return run_experiment(
        EXPERIMENT_ID,
        transformed,
        inputs.adapter,
        config,
        mis_solver_registry=builtin_mis_solver_registry(),
        classical_solver_registry=builtin_classical_solver_registry(),
        output_root=output_root,
        experiment_metadata=metadata,
    )
