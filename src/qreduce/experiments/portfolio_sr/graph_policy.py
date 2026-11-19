"""MWIS graph construction for Sharpe portfolio optimization.

This module builds the reduction graph for the MWIS auxiliary problem:
- Nodes represent assets available for selection
- Edges represent potential redundancy (high correlation, similar characteristics)
- Node weights are individual Sharpe ratios (normalized)

Edge semantics:
- correlation_only: edge if positive correlation >= threshold
- near_duplicate: edge if correlation AND similar return/variance

Important design decisions:
- Correlations are NOT taken in absolute value by default
- Only positive correlations create edges (redundancy, not hedging)
- Sector membership does NOT generate edges or penalties
- The graph is purely for domain reduction, not financial objectives
"""

from collections.abc import Sequence
from dataclasses import dataclass

from qreduce.experiments.portfolio_sr.formulation import compute_retention_scores
from qreduce.experiments.portfolio_sr.models import (
    SharpeGraphPolicy,
    SharpePortfolioProblem,
    TransformedSharpeProblem,
)
from qreduce.mwis import ReductionGraph


@dataclass(frozen=True, slots=True)
class EdgeCriteria:
    """Explanation of why an edge was or was not created."""

    ticker_a: str
    ticker_b: str
    correlation: float
    correlation_threshold: float
    correlation_passed: bool
    relative_return_diff: float | None
    max_return_diff: float | None
    return_diff_passed: bool | None
    relative_variance_diff: float | None
    max_variance_diff: float | None
    variance_diff_passed: bool | None
    edge_created: bool
    reason_code: str


def build_sharpe_reduction_graph(
    problem: SharpePortfolioProblem | TransformedSharpeProblem,
    policy: SharpeGraphPolicy,
    *,
    available_tickers: Sequence[str] | None = None,
) -> ReductionGraph:
    """Build MWIS reduction graph for Sharpe portfolio.

    Args:
        problem: The Sharpe portfolio problem (original or transformed).
        policy: Graph construction policy.
        available_tickers: Optional subset of tickers to include.
            If None, uses all tickers from the problem.

    Returns:
        ReductionGraph ready for MWIS solving.
    """
    # Get the original problem if transformed
    if isinstance(problem, TransformedSharpeProblem):
        original = problem.original_problem
        if available_tickers is None:
            available_tickers = problem.retained_tickers
    else:
        original = problem
        if available_tickers is None:
            available_tickers = original.tickers

    # Validate available tickers
    ticker_set = set(original.tickers)
    available = tuple(t for t in available_tickers if t in ticker_set)

    if not available:
        raise ValueError("No valid tickers available for graph construction.")

    # Compute node weights (individual Sharpe ratios)
    all_scores = compute_retention_scores(original, score_type="individual_sharpe")
    node_weights = {t: all_scores[t] for t in available}

    # Build edges
    edges: list[tuple[str, str]] = []
    edge_reasons: dict[tuple[str, str], str] = {}

    for i, ticker_a in enumerate(available):
        for ticker_b in available[i + 1:]:
            criteria = _evaluate_edge_criteria(
                original, ticker_a, ticker_b, policy
            )

            if criteria.edge_created:
                # Canonical edge ordering (lexicographic)
                edge = (ticker_a, ticker_b) if ticker_a < ticker_b else (ticker_b, ticker_a)
                edges.append(edge)
                edge_reasons[edge] = criteria.reason_code

    # Sort edges for determinism
    sorted_edges = tuple(sorted(edges))

    return ReductionGraph(
        node_ids=available,
        node_weights=node_weights,
        edges=sorted_edges,
        edge_reasons={e: edge_reasons[e] for e in sorted_edges},
        graph_policy_id=policy.policy_id,
        graph_policy_version=policy.policy_version,
    )


def _evaluate_edge_criteria(
    problem: SharpePortfolioProblem,
    ticker_a: str,
    ticker_b: str,
    policy: SharpeGraphPolicy,
) -> EdgeCriteria:
    """Evaluate whether an edge should be created between two tickers.

    Args:
        problem: The Sharpe portfolio problem.
        ticker_a: First ticker.
        ticker_b: Second ticker.
        policy: Graph construction policy.

    Returns:
        EdgeCriteria with full evaluation details.
    """
    # Compute correlation (NOT absolute value)
    correlation = problem.correlation(ticker_a, ticker_b)

    # Check correlation threshold
    # Only positive correlations create edges (redundancy)
    correlation_passed = correlation >= policy.correlation_threshold

    # Initialize near-duplicate fields
    relative_return_diff: float | None = None
    max_return_diff: float | None = None
    return_diff_passed: bool | None = None
    relative_variance_diff: float | None = None
    max_variance_diff: float | None = None
    variance_diff_passed: bool | None = None

    edge_created = False
    reason_parts: list[str] = [f"mode={policy.edge_mode}"]
    reason_parts.append(f"corr={correlation:.4f}")
    reason_parts.append(f"threshold={policy.correlation_threshold:.4f}")

    if policy.edge_mode == "correlation_only":
        if correlation_passed:
            edge_created = True
            reason_parts.append("EDGE:correlation_passed")
        else:
            reason_parts.append("NO_EDGE:correlation_below_threshold")

    elif policy.edge_mode == "near_duplicate":
        if not correlation_passed:
            reason_parts.append("NO_EDGE:correlation_below_threshold")
        else:
            # Check return similarity
            mu_a = problem.mean_returns[ticker_a]
            mu_b = problem.mean_returns[ticker_b]
            epsilon = 1e-12
            max_mu = max(abs(mu_a), abs(mu_b), epsilon)
            relative_return_diff = abs(mu_a - mu_b) / max_mu
            max_return_diff = policy.near_duplicate_max_return_diff

            assert max_return_diff is not None
            return_diff_passed = relative_return_diff <= max_return_diff

            # Check variance similarity
            var_a = problem.variance(ticker_a)
            var_b = problem.variance(ticker_b)
            max_var = max(var_a, var_b, epsilon)
            relative_variance_diff = abs(var_a - var_b) / max_var
            max_variance_diff = policy.near_duplicate_max_variance_diff

            assert max_variance_diff is not None
            variance_diff_passed = relative_variance_diff <= max_variance_diff

            reason_parts.append(f"return_diff={relative_return_diff:.4f}")
            reason_parts.append(f"max_return_diff={max_return_diff:.4f}")
            reason_parts.append(f"variance_diff={relative_variance_diff:.4f}")
            reason_parts.append(f"max_variance_diff={max_variance_diff:.4f}")

            if return_diff_passed and variance_diff_passed:
                edge_created = True
                reason_parts.append("EDGE:near_duplicate")
            else:
                if not return_diff_passed:
                    reason_parts.append("NO_EDGE:return_diff_exceeded")
                if not variance_diff_passed:
                    reason_parts.append("NO_EDGE:variance_diff_exceeded")

    reason_code = "; ".join(reason_parts)

    return EdgeCriteria(
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        correlation=correlation,
        correlation_threshold=policy.correlation_threshold,
        correlation_passed=correlation_passed,
        relative_return_diff=relative_return_diff,
        max_return_diff=max_return_diff,
        return_diff_passed=return_diff_passed,
        relative_variance_diff=relative_variance_diff,
        max_variance_diff=max_variance_diff,
        variance_diff_passed=variance_diff_passed,
        edge_created=edge_created,
        reason_code=reason_code,
    )


def default_sharpe_graph_policy(
    *,
    correlation_threshold: float = 0.80,
    edge_mode: str = "near_duplicate",
    near_duplicate_max_return_diff: float = 0.15,
    near_duplicate_max_variance_diff: float = 0.15,
) -> SharpeGraphPolicy:
    """Create a default graph policy for Sharpe portfolio.

    Args:
        correlation_threshold: Minimum positive correlation for edge.
        edge_mode: Either "correlation_only" or "near_duplicate".
        near_duplicate_max_return_diff: Max relative return difference.
        near_duplicate_max_variance_diff: Max relative variance difference.

    Returns:
        SharpeGraphPolicy with the specified parameters.
    """
    return SharpeGraphPolicy(
        policy_id="sharpe_portfolio_graph_policy",
        policy_version="1",
        correlation_threshold=correlation_threshold,
        edge_mode=edge_mode,  # type: ignore[arg-type]
        near_duplicate_max_return_diff=near_duplicate_max_return_diff,
        near_duplicate_max_variance_diff=near_duplicate_max_variance_diff,
    )


def compute_graph_statistics(graph: ReductionGraph) -> dict[str, object]:
    """Compute summary statistics for a reduction graph.

    Args:
        graph: The reduction graph.

    Returns:
        Dictionary of statistics.
    """
    n_nodes = len(graph.node_ids)
    n_edges = len(graph.edges)

    # Degree distribution
    degrees: dict[str, int] = {node: 0 for node in graph.node_ids}
    for a, b in graph.edges:
        degrees[a] += 1
        degrees[b] += 1

    degree_values = list(degrees.values())

    # Weight statistics
    weight_values = list(graph.node_weights.values())

    return {
        "node_count": n_nodes,
        "edge_count": n_edges,
        "density": 2 * n_edges / (n_nodes * (n_nodes - 1)) if n_nodes > 1 else 0,
        "degree_min": min(degree_values) if degree_values else 0,
        "degree_max": max(degree_values) if degree_values else 0,
        "degree_mean": sum(degree_values) / n_nodes if n_nodes > 0 else 0,
        "isolated_nodes": sum(1 for d in degree_values if d == 0),
        "weight_min": min(weight_values) if weight_values else 0,
        "weight_max": max(weight_values) if weight_values else 0,
        "weight_sum": sum(weight_values),
    }
