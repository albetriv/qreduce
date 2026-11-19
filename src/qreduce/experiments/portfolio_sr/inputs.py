"""Input factory for Sharpe portfolio experiment.

This module provides:
- build_sharpe_portfolio_inputs: main factory function
- SharpePortfolioInputs: bundled inputs ready for pipeline
- Universe selection and filtering
- Default policy configurations

The factory handles:
1. Loading price data from CSV
2. Computing return statistics (simple or log)
3. Filtering to positive mean returns
4. Universe selection (by count, explicit tickers, or all)
5. Building sector constraints
6. Creating the optimization problem
7. Configuring adapter and policies
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
from qreduce.experiments.portfolio_sr.datasets import (
    ReturnStatistics,
    SP500Dataset,
    compute_return_statistics,
    load_sp500_prices,
)
from qreduce.experiments.portfolio_sr.graph_policy import default_sharpe_graph_policy
from qreduce.experiments.portfolio_sr.models import (
    EdgeMode,
    SectorConstraints,
    SharpeGraphPolicy,
    SharpePortfolioProblem,
)
from qreduce.models import ReductionPolicy

# Default paths
DEFAULT_SP500_CSV = Path("data/yahoo/SP500.csv")
DEFAULT_OUTPUT_ROOT = Path("outputs/portfolio_sr")


@dataclass(frozen=True, slots=True)
class UniverseSelection:
    """Configuration for universe selection."""

    method: str  # "count", "explicit", "all"
    asset_count: int | None = None
    explicit_tickers: tuple[str, ...] | None = None
    random_seed: int | None = None
    selection_order: str = "alphabetical"  # "alphabetical", "sharpe_descending", "random"


@dataclass(frozen=True, slots=True)
class SharpePortfolioInputs:
    """Bundled inputs ready for pipeline execution."""

    problem: SharpePortfolioProblem
    adapter: SharpePortfolioAdapter
    graph_policy: SharpeGraphPolicy
    source_dataset: SP500Dataset
    return_statistics: ReturnStatistics
    universe_selection: UniverseSelection
    preprocessing_config: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        """Serialize inputs for artifact storage."""
        return {
            "problem": self.problem.to_dict(),
            "graph_policy": self.graph_policy.to_dict(),
            "source_dataset": self.source_dataset.to_dict(),
            "return_statistics": self.return_statistics.to_dict(),
            "universe_selection": {
                "method": self.universe_selection.method,
                "asset_count": self.universe_selection.asset_count,
                "explicit_tickers": list(self.universe_selection.explicit_tickers or []),
                "random_seed": self.universe_selection.random_seed,
                "selection_order": self.universe_selection.selection_order,
            },
            "preprocessing_config": dict(self.preprocessing_config),
        }


def build_sharpe_portfolio_inputs(
    *,
    csv_path: str | Path = DEFAULT_SP500_CSV,
    asset_count: int | None = None,
    explicit_tickers: Sequence[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    return_convention: str = "log",
    annualization_factor: int = 252,
    risk_free_rate: float = 0.0,
    upper_bound: float = 1.0,
    sector_constraints: SectorConstraints | None = None,
    max_positions: int | None = None,
    graph_policy: SharpeGraphPolicy | None = None,
    selection_order: str = "alphabetical",
    random_seed: int | None = None,
) -> SharpePortfolioInputs:
    """Build complete inputs for Sharpe portfolio experiment.

    Args:
        csv_path: Path to S&P500 price CSV file.
        asset_count: Number of assets to select (mutually exclusive with explicit_tickers).
        explicit_tickers: Specific tickers to include (mutually exclusive with asset_count).
        start_date: Optional start date for price data.
        end_date: Optional end date for price data.
        return_convention: "simple" or "log". Default: "log".
        annualization_factor: Trading days per year. Default: 252.
        risk_free_rate: Risk-free rate for Sharpe calculation. Default: 0.0.
        upper_bound: Maximum weight per asset. Default: 1.0.
        sector_constraints: Optional sector diversification constraints.
        max_positions: Optional maximum number of positions (cardinality constraint).
        graph_policy: MWIS graph construction policy. Default: near_duplicate mode.
        selection_order: How to order tickers for selection. Default: "alphabetical".
        random_seed: Random seed for reproducible random selection.

    Returns:
        SharpePortfolioInputs ready for pipeline execution.

    Raises:
        FileNotFoundError: If CSV file not found.
        ValueError: If parameters are invalid.
    """
    # Validate mutual exclusivity
    if asset_count is not None and explicit_tickers is not None:
        raise ValueError("asset_count and explicit_tickers are mutually exclusive.")

    if asset_count is not None and asset_count < 1:
        raise ValueError("asset_count must be at least 1.")

    # Load price data
    dataset = load_sp500_prices(
        csv_path,
        start_date=start_date,
        end_date=end_date,
    )

    # Compute return statistics
    if return_convention not in ("simple", "log"):
        raise ValueError(f"Invalid return_convention: {return_convention}")

    stats = compute_return_statistics(
        dataset,
        return_convention=return_convention,  # type: ignore[arg-type]
        annualization_factor=annualization_factor,
    )

    # Determine universe selection method
    if explicit_tickers is not None:
        selection = UniverseSelection(
            method="explicit",
            explicit_tickers=tuple(explicit_tickers),
        )
        selected_tickers = _select_explicit_tickers(stats, explicit_tickers)
    elif asset_count is not None:
        selection = UniverseSelection(
            method="count",
            asset_count=asset_count,
            random_seed=random_seed,
            selection_order=selection_order,
        )
        selected_tickers = _select_by_count(
            stats, asset_count, selection_order, random_seed
        )
    else:
        selection = UniverseSelection(method="all")
        selected_tickers = stats.tickers

    # Build sector mapping for selected tickers
    sectors = {t: dataset.sectors[t] for t in selected_tickers}

    # Build sector constraints if provided, with validation
    if sector_constraints is not None:
        available_sectors = set(sectors.values())
        known_sectors = set(dataset.sectors.values())
        sector_constraints = _filter_sector_constraints(
            sector_constraints, available_sectors, known_sectors
        )

    # Build upper bounds
    upper_bounds = {t: upper_bound for t in selected_tickers}

    # Build covariance submatrix
    ticker_indices = [stats.tickers.index(t) for t in selected_tickers]
    covariance = tuple(
        tuple(stats.covariance[i][j] for j in ticker_indices)
        for i in ticker_indices
    )

    # Build mean returns
    mean_returns = {t: stats.mean_returns[t] for t in selected_tickers}

    # Create problem
    problem = SharpePortfolioProblem(
        tickers=selected_tickers,
        mean_returns=mean_returns,
        covariance=covariance,
        sectors=sectors,
        upper_bounds=upper_bounds,
        sector_constraints=sector_constraints,
        max_positions=max_positions,
        risk_free_rate=risk_free_rate,
        _covariance_validated=True,  # Already validated in compute_return_statistics
    )

    # Create graph policy
    if graph_policy is None:
        graph_policy = default_sharpe_graph_policy()

    # Create adapter
    adapter = SharpePortfolioAdapter(graph_policy)

    # Build preprocessing config for provenance
    preprocessing_config: dict[str, object] = {
        "csv_path": str(csv_path),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "return_convention": return_convention,
        "annualization_factor": annualization_factor,
        "risk_free_rate": risk_free_rate,
        "upper_bound": upper_bound,
        "max_positions": max_positions,
    }

    return SharpePortfolioInputs(
        problem=problem,
        adapter=adapter,
        graph_policy=graph_policy,
        source_dataset=dataset,
        return_statistics=stats,
        universe_selection=selection,
        preprocessing_config=MappingProxyType(preprocessing_config),
    )


def _select_explicit_tickers(
    stats: ReturnStatistics,
    requested: Sequence[str],
) -> tuple[str, ...]:
    """Select explicitly requested tickers.

    Args:
        stats: Return statistics with eligible tickers.
        requested: Requested ticker list.

    Returns:
        Tuple of validated tickers.

    Raises:
        ValueError: If any requested ticker is invalid.
    """
    available = set(stats.tickers)
    missing = [t for t in requested if t not in available]

    if missing:
        # Check if they were excluded due to non-positive returns
        excluded_positive = [
            t for t in missing
            if t in stats.exclusion_reasons
        ]
        truly_missing = [t for t in missing if t not in stats.exclusion_reasons]

        error_parts = []
        if truly_missing:
            error_parts.append(f"Unknown tickers: {truly_missing}")
        if excluded_positive:
            error_parts.append(
                f"Tickers with non-positive mean returns: {excluded_positive}"
            )
        raise ValueError("; ".join(error_parts))

    return tuple(requested)


def _select_by_count(
    stats: ReturnStatistics,
    count: int,
    order: str,
    seed: int | None,
) -> tuple[str, ...]:
    """Select tickers by count with specified ordering.

    Args:
        stats: Return statistics with eligible tickers.
        count: Number of tickers to select.
        order: Selection order ("alphabetical", "sharpe_descending", "random").
        seed: Random seed for reproducible random selection.

    Returns:
        Tuple of selected tickers.

    Raises:
        ValueError: If count exceeds available tickers.
    """
    available = list(stats.tickers)

    if count > len(available):
        raise ValueError(
            f"Requested {count} assets but only {len(available)} have positive mean returns."
        )

    if order == "alphabetical":
        # Already sorted alphabetically from stats
        return tuple(available[:count])

    elif order == "sharpe_descending":
        # Sort by individual Sharpe ratio (mu/sigma), descending
        def sharpe_key(ticker: str) -> float:
            mu = stats.mean_returns[ticker]
            i = stats.tickers.index(ticker)
            sigma = math.sqrt(stats.covariance[i][i])
            return -mu / sigma if sigma > 0 else 0  # Negative for descending

        sorted_tickers = sorted(available, key=sharpe_key)
        return tuple(sorted_tickers[:count])

    elif order == "random":
        import random
        rng = random.Random(seed)
        shuffled = available.copy()
        rng.shuffle(shuffled)
        return tuple(shuffled[:count])

    else:
        raise ValueError(f"Unknown selection_order: {order}")


def _filter_sector_constraints(
    constraints: SectorConstraints,
    available_sectors: set[str],
    known_sectors: set[str],
) -> SectorConstraints:
    """Validate and filter sector constraints for selected universe.

    Validation rules:
    1. Unknown sector (not in known_sectors): ERROR - likely typo
    2. Known sector absent from universe with min > 0: ERROR - infeasible
    3. Known sector absent from universe with min = 0: OK - trivially satisfied

    Args:
        constraints: Original sector constraints from user.
        available_sectors: Sectors present in selected universe.
        known_sectors: All sectors in the full dataset (for typo detection).

    Returns:
        Validated SectorConstraints filtered to available sectors.

    Raises:
        ValueError: If any sector is unknown or has positive minimum but
            is absent from the universe.
    """
    errors: list[str] = []

    # Check for unknown sectors (typo detection)
    for sector in constraints.sectors:
        if sector not in known_sectors:
            errors.append(
                f"Unknown sector '{sector}' in constraints. "
                f"Known sectors: {sorted(known_sectors)}"
            )

    if errors:
        raise ValueError("Sector constraint validation failed:\n" + "\n".join(errors))

    # Check for infeasible constraints (sector with min > 0 not in universe)
    for sector in constraints.sectors:
        min_val = constraints.sector_min[sector]
        if sector not in available_sectors and min_val > 0:
            errors.append(
                f"Sector '{sector}' has minimum constraint {min_val:.2%} but "
                f"no tickers from this sector are in the selected universe. "
                "Either include tickers from this sector, set minimum to 0, "
                "or remove the constraint."
            )

    if errors:
        raise ValueError("Sector constraint validation failed:\n" + "\n".join(errors))

    # Build filtered constraints for sectors present in universe
    filtered_min: dict[str, float] = {}
    filtered_max: dict[str, float] = {}

    for sector in constraints.sectors:
        if sector in available_sectors:
            filtered_min[sector] = constraints.sector_min[sector]
            filtered_max[sector] = constraints.sector_max[sector]
        # Sectors with min=0 not in universe are simply not included
        # (trivially satisfied, documented in preprocessing_config)

    # Add default bounds for sectors in universe not in original constraints
    for sector in available_sectors:
        if sector not in filtered_min:
            filtered_min[sector] = 0.0
            filtered_max[sector] = 1.0

    return SectorConstraints(
        sector_min=filtered_min,
        sector_max=filtered_max,
    )


def default_reduction_policy(
    asset_count: int,
    *,
    max_reduction_rounds: int = 1,
    has_cardinality: bool = False,
) -> ReductionPolicy:
    """Create default reduction policy for Sharpe portfolio.

    Args:
        asset_count: Number of assets in the problem.
        max_reduction_rounds: Maximum reduction rounds (0=baseline, 1=single, >1=multi).
        has_cardinality: Whether the problem has cardinality constraints (binary variables).

    Returns:
        ReductionPolicy with sensible defaults.

    Notes:
        When has_cardinality=False, target_binary_variables is set to 0 to disable
        the binary variable target criterion (since there are no binary variables
        in the continuous-only problem).
    """
    # Target around 60% of assets as candidate domain
    max_items = max(1, int(asset_count * 0.6))

    # target_binary_variables only makes sense when there are binary variables
    # (i.e., when cardinality constraint is present)
    if has_cardinality:
        target_binaries = 3  # Standard target for small residual
    else:
        target_binaries = 0  # Disable this criterion for continuous problems

    return ReductionPolicy(
        max_reduction_rounds=max_reduction_rounds,
        candidate_domain_min_items=1,
        candidate_domain_max_items=max_items,
        num_source_mis_candidates=1,
        min_reduction_ratio=0.1,
        target_binary_variables=target_binaries,
        max_end_to_end_runtime_seconds=120.0,
        recovery_policy_on_domain_too_small="fail",
        recovery_policy_on_infeasible="fail",
        max_recovery_attempts=0,
    )


def default_graph_policy_for_sharpe(
    *,
    edge_mode: EdgeMode = "near_duplicate",
    correlation_threshold: float = 0.80,
    near_duplicate_max_return_diff: float = 0.15,
    near_duplicate_max_variance_diff: float = 0.15,
) -> SharpeGraphPolicy:
    """Create graph policy for Sharpe portfolio.

    Args:
        edge_mode: Edge semantics ("correlation_only" or "near_duplicate").
        correlation_threshold: Minimum positive correlation for edge.
        near_duplicate_max_return_diff: Max relative return difference.
        near_duplicate_max_variance_diff: Max relative variance difference.

    Returns:
        SharpeGraphPolicy with specified parameters.
    """
    return default_sharpe_graph_policy(
        edge_mode=edge_mode,
        correlation_threshold=correlation_threshold,
        near_duplicate_max_return_diff=near_duplicate_max_return_diff,
        near_duplicate_max_variance_diff=near_duplicate_max_variance_diff,
    )
