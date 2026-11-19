"""Portfolio presentation data reconstructed from persisted artifacts."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from qreduce.experiments.artifacts import (
    ExperimentArtifactError,
    ExperimentRunArtifacts,
    load_experiment_run,
)
from qreduce.experiments.portfolio_mv.execution import UNIFIED_EXPERIMENT_ID
from qreduce.experiments.portfolio_mv.inputs import SYNTHETIC_PORTFOLIO_EXPERIMENT_ID
from qreduce.mwis import ReductionGraph

# Accept both legacy and unified experiment IDs for single-pass compatible analysis
_SINGLE_PASS_COMPATIBLE_IDS = frozenset({
    SYNTHETIC_PORTFOLIO_EXPERIMENT_ID,  # legacy: synthetic-portfolio-single-pass
    UNIFIED_EXPERIMENT_ID,  # new: synthetic-portfolio
})

# Accept both legacy and unified experiment IDs for multi-round compatible analysis
_MULTI_ROUND_COMPATIBLE_IDS = frozenset({
    "synthetic-portfolio-multi-round",  # legacy
    UNIFIED_EXPERIMENT_ID,  # new: synthetic-portfolio
})

# All portfolio experiment IDs accepted by the universal solution loader
_ALL_PORTFOLIO_IDS = _SINGLE_PASS_COMPATIBLE_IDS | _MULTI_ROUND_COMPATIBLE_IDS


def _compute_solution_summary(
    asset_ids: tuple[str, ...],
    retained_item_ids: tuple[str, ...] | None,
    artifacts_result: Mapping[str, object],
    integrality_tolerance: float,
    weight_tolerance: float,
) -> dict[str, object]:
    """Compute solution summary with retained_count independent of solution validity.

    This is the shared implementation used by both PortfolioSolutionAnalysis and
    SyntheticPortfolioAnalysis.

    Args:
        asset_ids: Ordered asset identifiers.
        retained_item_ids: Asset IDs retained in candidate domain (None if no reduction).
        artifacts_result: The run result dict containing classical_result.
        integrality_tolerance: Tolerance for binary variable to be considered 1.
        weight_tolerance: Tolerance for weight to be considered positive.

    Returns:
        Dictionary with summary counts and flags.
    """
    # Validate tolerances
    if not math.isfinite(integrality_tolerance) or integrality_tolerance < 0:
        raise ValueError("integrality_tolerance must be a finite non-negative number")
    if not math.isfinite(weight_tolerance) or weight_tolerance < 0:
        raise ValueError("weight_tolerance must be a finite non-negative number")

    # retained_count is computed from retained_item_ids, independent of solution validity
    if retained_item_ids is None:
        retained_count = None
    else:
        retained_count = len(retained_item_ids)

    # Check if solution data is available
    classical_result = artifacts_result.get("classical_result")
    if not isinstance(classical_result, dict):
        return {
            "total_assets": len(asset_ids),
            "retained_count": retained_count,
            "selected_count": None,
            "invested_count": None,
            "selected_but_not_invested": None,
            "total_weight": None,
            "valid_count": 0,
            "invalid_count": len(asset_ids),
            "is_complete": False,
            "tolerances": {
                "integrality_tolerance": integrality_tolerance,
                "weight_tolerance": weight_tolerance,
            },
        }

    variable_values = classical_result.get("variable_values")
    if not isinstance(variable_values, dict):
        return {
            "total_assets": len(asset_ids),
            "retained_count": retained_count,
            "selected_count": None,
            "invested_count": None,
            "selected_but_not_invested": None,
            "total_weight": None,
            "valid_count": 0,
            "invalid_count": len(asset_ids),
            "is_complete": False,
            "tolerances": {
                "integrality_tolerance": integrality_tolerance,
                "weight_tolerance": weight_tolerance,
            },
        }

    # Count solution-derived metrics
    selected_count = 0
    invested_count = 0
    selected_but_not_invested = 0
    total_weight = 0.0
    valid_count = 0
    invalid_count = 0

    for asset_id in asset_ids:
        delta_name = f"delta__{asset_id}"
        x_name = f"x__{asset_id}"

        delta_value = variable_values.get(delta_name)
        x_value = variable_values.get(x_name)

        # Check validity
        is_valid = (
            isinstance(delta_value, int | float)
            and isinstance(x_value, int | float)
            and not isinstance(delta_value, bool)
            and not isinstance(x_value, bool)
            and math.isfinite(delta_value)
            and math.isfinite(x_value)
        )

        if not is_valid:
            invalid_count += 1
            continue

        valid_count += 1

        is_selected = abs(delta_value - 1.0) <= integrality_tolerance
        is_invested = x_value > weight_tolerance

        if is_selected:
            selected_count += 1
            if not is_invested:
                selected_but_not_invested += 1

        if is_invested:
            invested_count += 1

        if x_value > 0:
            total_weight += x_value

    is_complete = invalid_count == 0

    return {
        "total_assets": len(asset_ids),
        "retained_count": retained_count,
        "selected_count": selected_count,
        "invested_count": invested_count,
        "selected_but_not_invested": selected_but_not_invested,
        "total_weight": total_weight,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "is_complete": is_complete,
        "tolerances": {
            "integrality_tolerance": integrality_tolerance,
            "weight_tolerance": weight_tolerance,
        },
    }


def _compute_solution_selection_rows(
    asset_ids: tuple[str, ...],
    retained_item_ids: tuple[str, ...] | None,
    artifacts_result: Mapping[str, object],
    integrality_tolerance: float,
    weight_tolerance: float,
) -> list[dict[str, object]]:
    """Compute per-asset solution status rows.

    This is the shared implementation used by both PortfolioSolutionAnalysis and
    SyntheticPortfolioAnalysis.

    Args:
        asset_ids: Ordered asset identifiers.
        retained_item_ids: Asset IDs retained in candidate domain (None if no reduction).
        artifacts_result: The run result dict containing classical_result.
        integrality_tolerance: Tolerance for binary variable to be considered 1.
        weight_tolerance: Tolerance for weight to be considered positive.

    Returns:
        List of dicts with per-asset solution status.
    """
    # Validate tolerances
    if not math.isfinite(integrality_tolerance) or integrality_tolerance < 0:
        raise ValueError("integrality_tolerance must be a finite non-negative number")
    if not math.isfinite(weight_tolerance) or weight_tolerance < 0:
        raise ValueError("weight_tolerance must be a finite non-negative number")

    classical_result = artifacts_result.get("classical_result")
    if not isinstance(classical_result, dict):
        return []

    variable_values = classical_result.get("variable_values")
    if not isinstance(variable_values, dict):
        return []

    retained_set = None if retained_item_ids is None else set(retained_item_ids)

    rows: list[dict[str, object]] = []
    for asset_id in asset_ids:
        delta_name = f"delta__{asset_id}"
        x_name = f"x__{asset_id}"

        delta_value = variable_values.get(delta_name)
        x_value = variable_values.get(x_name)

        is_retained = None if retained_set is None else asset_id in retained_set

        # Check for missing values
        if delta_value is None or x_value is None:
            rows.append({
                "asset": asset_id,
                "retained": is_retained,
                "selected": None,
                "invested": None,
                "delta": None,
                "weight": None,
                "valid": False,
            })
            continue

        # Check for non-numeric values (including bool which is subclass of int)
        if (
            not isinstance(delta_value, int | float)
            or not isinstance(x_value, int | float)
            or isinstance(delta_value, bool)
            or isinstance(x_value, bool)
        ):
            rows.append({
                "asset": asset_id,
                "retained": is_retained,
                "selected": None,
                "invested": None,
                "delta": None,
                "weight": None,
                "valid": False,
            })
            continue

        # Check for non-finite values (NaN, inf)
        delta_finite = math.isfinite(delta_value)
        x_finite = math.isfinite(x_value)
        is_valid = delta_finite and x_finite

        if not is_valid:
            rows.append({
                "asset": asset_id,
                "retained": is_retained,
                "selected": None,
                "invested": None,
                "delta": delta_value,
                "weight": x_value,
                "valid": False,
            })
            continue

        is_selected = abs(delta_value - 1.0) <= integrality_tolerance
        is_invested = x_value > weight_tolerance

        rows.append({
            "asset": asset_id,
            "retained": is_retained,
            "selected": is_selected,
            "invested": is_invested,
            "delta": delta_value,
            "weight": x_value,
            "valid": True,
        })

    return rows


@dataclass(frozen=True, slots=True)
class PortfolioSolutionAnalysis:
    """Solution-focused presentation data that works for both baseline and reduction runs.

    This class provides solution analysis without requiring MWIS graph data,
    making it suitable for classical-only baseline runs as well as reduction runs.
    It accepts all portfolio experiment types including legacy multi-round.

    Attributes:
        artifacts: The raw experiment artifacts
        asset_ids: Ordered asset identifiers
        correlation: Correlation matrix derived from covariance (or None if unavailable)
        correlation_threshold: Threshold used for graph edges (or None if no graph policy)
        retained_item_ids: Asset IDs retained in the final domain (or None if no reduction)
        lower_bounds: Per-asset minimum investment (conditional on selection)
        upper_bounds: Per-asset maximum investment (conditional on selection)
        min_selected_assets: Minimum cardinality constraint (or None if unconstrained)
        max_selected_assets: Maximum cardinality constraint (or None if unconstrained)
        is_classical_only: True if this was a baseline run with no reduction
    """

    artifacts: ExperimentRunArtifacts
    asset_ids: tuple[str, ...]
    correlation: tuple[tuple[float, ...], ...] | None
    correlation_threshold: float | None
    retained_item_ids: tuple[str, ...] | None
    lower_bounds: Mapping[str, float] | None
    upper_bounds: Mapping[str, float] | None
    min_selected_assets: int | None
    max_selected_assets: int | None
    is_classical_only: bool

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

    def cardinality_summary(self) -> dict[str, object]:
        """Return summary of cardinality and investment bound constraints.

        Returns:
            Dictionary with:
            - min_selected_assets: minimum cardinality or None
            - max_selected_assets: maximum cardinality or None
            - has_cardinality_constraint: True if any cardinality constraint is set
            - uniform_lower_bound: lower bound if all are equal, else None
            - uniform_upper_bound: upper bound if all are equal, else None
            - has_positive_minimum: True if any lower bound > 0
        """
        has_cardinality = self.min_selected_assets is not None or self.max_selected_assets is not None

        uniform_lower = None
        uniform_upper = None
        has_positive_min = False

        if self.lower_bounds:
            values = set(self.lower_bounds.values())
            if len(values) == 1:
                uniform_lower = next(iter(values))
            has_positive_min = any(v > 0 for v in self.lower_bounds.values())

        if self.upper_bounds:
            values = set(self.upper_bounds.values())
            if len(values) == 1:
                uniform_upper = next(iter(values))

        return {
            "min_selected_assets": self.min_selected_assets,
            "max_selected_assets": self.max_selected_assets,
            "has_cardinality_constraint": has_cardinality,
            "uniform_lower_bound": uniform_lower,
            "uniform_upper_bound": uniform_upper,
            "has_positive_minimum": has_positive_min,
        }

    def investment_bounds_rows(self) -> list[dict[str, object]]:
        """Return per-asset investment bounds for tables."""
        if self.lower_bounds is None or self.upper_bounds is None:
            return []
        return [
            {
                "asset": asset_id,
                "lower_bound": self.lower_bounds.get(asset_id),
                "upper_bound": self.upper_bounds.get(asset_id),
            }
            for asset_id in self.asset_ids
        ]

    def solution_selection_rows(
        self,
        integrality_tolerance: float = 1e-5,
        weight_tolerance: float = 1e-8,
    ) -> list[dict[str, object]]:
        """Return per-asset solution status distinguishing retained, selected, and invested.

        This method extracts solution values from the classical result and
        categorizes each asset into three distinct states:
        - retained: Asset was kept in the candidate domain (not fixed to zero)
        - selected: Binary variable delta ≈ 1 (within integrality_tolerance)
        - invested: Continuous weight x > weight_tolerance and is finite

        When lower_bound > 0, selected implies invested (within tolerance).
        When lower_bound = 0, an asset can be selected (delta=1) but have zero weight.

        Args:
            integrality_tolerance: Tolerance for binary variable to be considered 1.
                Must be finite and non-negative.
            weight_tolerance: Tolerance for weight to be considered positive.
                Must be finite and non-negative.

        Returns:
            List of dicts with keys: asset, retained, selected, invested, delta, weight, valid.
            The 'valid' key is True if both delta and weight are finite numbers.
            Returns empty list if solution data is not available.

        Raises:
            ValueError: If tolerances are not finite non-negative numbers.
        """
        return _compute_solution_selection_rows(
            self.asset_ids,
            self.retained_item_ids,
            self.artifacts.result,
            integrality_tolerance,
            weight_tolerance,
        )

    def solution_summary(
        self,
        integrality_tolerance: float = 1e-5,
        weight_tolerance: float = 1e-8,
    ) -> dict[str, object]:
        """Return aggregate counts distinguishing retained, selected, and invested assets.

        The retained_count is computed from retained_item_ids and is independent of
        whether solution values are valid. This ensures the domain size is always
        accurate even when solution data is partial or missing.

        Args:
            integrality_tolerance: Tolerance for binary variable to be considered 1.
                Must be finite and non-negative.
            weight_tolerance: Tolerance for weight to be considered positive.
                Must be finite and non-negative.

        Returns:
            Dictionary with:
            - total_assets: Total number of assets in the problem
            - retained_count: Assets in the candidate domain (None if no reduction,
              computed independently from solution validity)
            - selected_count: Assets with delta ≈ 1 (among valid assets only)
            - invested_count: Assets with weight > tolerance (among valid assets only)
            - selected_but_not_invested: Assets with delta=1 but weight ≤ tolerance
            - total_weight: Sum of all positive finite weights
            - valid_count: Number of assets with valid (finite) solution values
            - invalid_count: Number of assets with missing or non-finite values
            - is_complete: True if all assets have valid solution values
            - tolerances: Dict with integrality_tolerance and weight_tolerance used

        Raises:
            ValueError: If tolerances are not finite non-negative numbers.
        """
        return _compute_solution_summary(
            self.asset_ids,
            self.retained_item_ids,
            self.artifacts.result,
            integrality_tolerance,
            weight_tolerance,
        )


def load_portfolio_solution_analysis(
    run_directory: str | Path,
) -> PortfolioSolutionAnalysis:
    """Load solution-focused presentation data for any portfolio experiment.

    This loader works for all portfolio experiment types:
    - Classical-only baseline runs (max_reduction_rounds=0)
    - Single-pass reduction runs
    - Multi-round reduction runs (including legacy synthetic-portfolio-multi-round)

    It does not require MWIS graph data, making it suitable for solution analysis
    without graph visualization.

    Args:
        run_directory: Path to the experiment run directory.

    Returns:
        PortfolioSolutionAnalysis with solution data extracted from artifacts.

    Raises:
        ExperimentArtifactError: If the artifact is not a portfolio experiment
            or required data is missing.
    """
    artifacts = load_experiment_run(run_directory)
    experiment_id = artifacts.manifest["experiment_id"]
    if experiment_id not in _ALL_PORTFOLIO_IDS:
        raise ExperimentArtifactError(
            f"Artifact directory does not contain a portfolio experiment. "
            f"Found experiment_id={experiment_id!r}, expected one of: "
            f"{', '.join(sorted(_ALL_PORTFOLIO_IDS))}."
        )

    problem = _require_mapping(artifacts.problem, "problem.json")
    asset_ids = _string_tuple(problem.get("asset_ids"), "problem.asset_ids")

    # Correlation is optional for solution analysis
    correlation = None
    try:
        covariance = _numeric_matrix(problem.get("covariance"), len(asset_ids), "problem.covariance")
        correlation = _correlation_matrix(covariance)
    except ExperimentArtifactError:
        pass

    # Threshold is optional (not present in baseline runs)
    correlation_threshold = None
    policy = artifacts.experiment_metadata.get("portfolio_graph_policy")
    if isinstance(policy, dict):
        threshold_value = policy.get("correlation_absolute_threshold")
        if isinstance(threshold_value, int | float) and math.isfinite(threshold_value):
            correlation_threshold = float(threshold_value)

    retained_item_ids = _retained_item_ids(artifacts.result)

    # Extract investment bounds and cardinality from problem (if present)
    lower_bounds = _extract_bounds(problem, "lower_bounds")
    upper_bounds = _extract_bounds(problem, "upper_bounds")
    min_selected_assets = _extract_optional_int(problem, "min_selected_assets")
    max_selected_assets = _extract_optional_int(problem, "max_selected_assets")

    is_classical_only = artifacts.is_classical_only

    return PortfolioSolutionAnalysis(
        artifacts=artifacts,
        asset_ids=asset_ids,
        correlation=correlation,
        correlation_threshold=correlation_threshold,
        retained_item_ids=retained_item_ids,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        min_selected_assets=min_selected_assets,
        max_selected_assets=max_selected_assets,
        is_classical_only=is_classical_only,
    )


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioAnalysis:
    """Notebook-facing presentation data reconstructed exclusively from saved artifacts.

    This class requires MWIS graph data and is suitable for runs with reduction.
    For baseline (classical-only) runs, use PortfolioSolutionAnalysis instead.

    Attributes:
        artifacts: The raw experiment artifacts
        graph: The reduction graph
        asset_ids: Ordered asset identifiers
        correlation: Correlation matrix derived from covariance
        correlation_threshold: Threshold used for graph edges
        retained_item_ids: Asset IDs retained in the final domain (or None if no reduction)
        lower_bounds: Per-asset minimum investment (conditional on selection)
        upper_bounds: Per-asset maximum investment (conditional on selection)
        min_selected_assets: Minimum cardinality constraint (or None if unconstrained)
        max_selected_assets: Maximum cardinality constraint (or None if unconstrained)
    """

    artifacts: ExperimentRunArtifacts
    graph: ReductionGraph
    asset_ids: tuple[str, ...]
    correlation: tuple[tuple[float, ...], ...]
    correlation_threshold: float
    retained_item_ids: tuple[str, ...] | None
    lower_bounds: Mapping[str, float] | None = None
    upper_bounds: Mapping[str, float] | None = None
    min_selected_assets: int | None = None
    max_selected_assets: int | None = None

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

    def cardinality_summary(self) -> dict[str, object]:
        """Return summary of cardinality and investment bound constraints.

        Returns:
            Dictionary with:
            - min_selected_assets: minimum cardinality or None
            - max_selected_assets: maximum cardinality or None
            - has_cardinality_constraint: True if any cardinality constraint is set
            - uniform_lower_bound: lower bound if all are equal, else None
            - uniform_upper_bound: upper bound if all are equal, else None
            - has_positive_minimum: True if any lower bound > 0
        """
        has_cardinality = self.min_selected_assets is not None or self.max_selected_assets is not None

        uniform_lower = None
        uniform_upper = None
        has_positive_min = False

        if self.lower_bounds:
            values = set(self.lower_bounds.values())
            if len(values) == 1:
                uniform_lower = next(iter(values))
            has_positive_min = any(v > 0 for v in self.lower_bounds.values())

        if self.upper_bounds:
            values = set(self.upper_bounds.values())
            if len(values) == 1:
                uniform_upper = next(iter(values))

        return {
            "min_selected_assets": self.min_selected_assets,
            "max_selected_assets": self.max_selected_assets,
            "has_cardinality_constraint": has_cardinality,
            "uniform_lower_bound": uniform_lower,
            "uniform_upper_bound": uniform_upper,
            "has_positive_minimum": has_positive_min,
        }

    def investment_bounds_rows(self) -> list[dict[str, object]]:
        """Return per-asset investment bounds for tables."""
        if self.lower_bounds is None or self.upper_bounds is None:
            return []
        return [
            {
                "asset": asset_id,
                "lower_bound": self.lower_bounds.get(asset_id),
                "upper_bound": self.upper_bounds.get(asset_id),
            }
            for asset_id in self.asset_ids
        ]

    def solution_selection_rows(
        self,
        integrality_tolerance: float = 1e-5,
        weight_tolerance: float = 1e-8,
    ) -> list[dict[str, object]]:
        """Return per-asset solution status distinguishing retained, selected, and invested.

        This method extracts solution values from the classical result and
        categorizes each asset into three distinct states:
        - retained: Asset was kept in the candidate domain (not fixed to zero)
        - selected: Binary variable delta ≈ 1 (within integrality_tolerance)
        - invested: Continuous weight x > weight_tolerance and is finite

        When lower_bound > 0, selected implies invested (within tolerance).
        When lower_bound = 0, an asset can be selected (delta=1) but have zero weight.

        Args:
            integrality_tolerance: Tolerance for binary variable to be considered 1.
                Must be finite and non-negative.
            weight_tolerance: Tolerance for weight to be considered positive.
                Must be finite and non-negative.

        Returns:
            List of dicts with keys: asset, retained, selected, invested, delta, weight, valid.
            The 'valid' key is True if both delta and weight are finite numbers.
            Returns empty list if solution data is not available.

        Raises:
            ValueError: If tolerances are not finite non-negative numbers.
        """
        return _compute_solution_selection_rows(
            self.asset_ids,
            self.retained_item_ids,
            self.artifacts.result,
            integrality_tolerance,
            weight_tolerance,
        )

    def solution_summary(
        self,
        integrality_tolerance: float = 1e-5,
        weight_tolerance: float = 1e-8,
    ) -> dict[str, object]:
        """Return aggregate counts distinguishing retained, selected, and invested assets.

        The retained_count is computed from retained_item_ids and is independent of
        whether solution values are valid. This ensures the domain size is always
        accurate even when solution data is partial or missing.

        Args:
            integrality_tolerance: Tolerance for binary variable to be considered 1.
                Must be finite and non-negative.
            weight_tolerance: Tolerance for weight to be considered positive.
                Must be finite and non-negative.

        Returns:
            Dictionary with:
            - total_assets: Total number of assets in the problem
            - retained_count: Assets in the candidate domain (None if no reduction,
              computed independently from solution validity)
            - selected_count: Assets with delta ≈ 1 (among valid assets only)
            - invested_count: Assets with weight > tolerance (among valid assets only)
            - selected_but_not_invested: Assets with delta=1 but weight ≤ tolerance
            - total_weight: Sum of all positive finite weights
            - valid_count: Number of assets with valid (finite) solution values
            - invalid_count: Number of assets with missing or non-finite values
            - is_complete: True if all assets have valid solution values
            - tolerances: Dict with integrality_tolerance and weight_tolerance used

        Raises:
            ValueError: If tolerances are not finite non-negative numbers.
        """
        return _compute_solution_summary(
            self.asset_ids,
            self.retained_item_ids,
            self.artifacts.result,
            integrality_tolerance,
            weight_tolerance,
        )


def load_synthetic_portfolio_analysis(
    run_directory: str | Path,
) -> SyntheticPortfolioAnalysis:
    """Load and validate presentation data for the synthetic portfolio experiment.

    Accepts runs from both legacy (synthetic-portfolio-single-pass) and unified
    (synthetic-portfolio) experiment IDs.
    """
    artifacts = load_experiment_run(run_directory)
    experiment_id = artifacts.manifest["experiment_id"]
    if experiment_id not in _SINGLE_PASS_COMPATIBLE_IDS:
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

    # Extract investment bounds and cardinality from problem (if present)
    lower_bounds = _extract_bounds(problem, "lower_bounds")
    upper_bounds = _extract_bounds(problem, "upper_bounds")
    min_selected_assets = _extract_optional_int(problem, "min_selected_assets")
    max_selected_assets = _extract_optional_int(problem, "max_selected_assets")

    return SyntheticPortfolioAnalysis(
        artifacts=artifacts,
        graph=graph,
        asset_ids=asset_ids,
        correlation=_correlation_matrix(covariance),
        correlation_threshold=threshold,
        retained_item_ids=retained_item_ids,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        min_selected_assets=min_selected_assets,
        max_selected_assets=max_selected_assets,
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


def _extract_bounds(problem: Mapping[str, object], key: str) -> Mapping[str, float] | None:
    """Extract lower_bounds or upper_bounds from problem, returning None if not present."""
    bounds_data = problem.get(key)
    if bounds_data is None:
        return None
    if not isinstance(bounds_data, dict):
        return None
    try:
        return {
            str(k): _finite_float(v, f"problem.{key}[{k!r}]")
            for k, v in bounds_data.items()
        }
    except ExperimentArtifactError:
        return None


def _extract_optional_int(problem: Mapping[str, object], key: str) -> int | None:
    """Extract an optional integer field from problem."""
    value = problem.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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


def load_multi_round_correlation_data(run_directory: str | Path):
    """Load input correlations and, when available, the persisted first-round graph.

    Accepts runs from both legacy (synthetic-portfolio-multi-round) and unified
    (synthetic-portfolio) experiment IDs. For unified experiments, only multi-round
    runs (max_reduction_rounds > 1) are accepted.

    Args:
        run_directory: Path to the experiment run directory.

    Returns:
        Tuple of (asset_ids, correlation_matrix, graph_or_none).

    Raises:
        ExperimentArtifactError: If the artifact is not a multi-round portfolio
            experiment, or if a unified run has max_reduction_rounds <= 1.
    """
    artifacts = load_experiment_run(run_directory)
    experiment_id = artifacts.manifest["experiment_id"]
    if experiment_id not in _MULTI_ROUND_COMPATIBLE_IDS:
        raise ExperimentArtifactError("Artifact directory is not a multi-round portfolio experiment.")

    # For unified experiment ID, verify this is actually a multi-round configuration
    if experiment_id == UNIFIED_EXPERIMENT_ID:
        max_rounds = artifacts.config.get("reduction", {}).get("max_reduction_rounds", 1)
        if max_rounds <= 1:
            raise ExperimentArtifactError(
                f"This loader requires a multi-round configuration (max_reduction_rounds > 1), "
                f"but the loaded run has max_reduction_rounds={max_rounds}. "
                f"Use load_synthetic_portfolio_analysis for single-pass runs."
            )

    problem = _require_mapping(artifacts.problem, "problem.json")
    asset_ids = _string_tuple(problem.get("asset_ids"), "problem.asset_ids")
    covariance = _numeric_matrix(problem.get("covariance"), len(asset_ids), "problem.covariance")
    graph = None
    if artifacts.round_results:
        compilation = artifacts.round_results[0].get("mis_compilation_result") or {}
        job = compilation.get("compiled_job") or {}
        compiled = job.get("compiled_problem") or {}
        graph_data = compiled.get("graph")
        if graph_data is not None:
            nodes = _string_tuple(graph_data.get("node_ids"), "graph.node_ids")
            if nodes != asset_ids:
                raise ExperimentArtifactError("First-round graph order does not match the portfolio.")
            edges = tuple(tuple(edge) for edge in graph_data["edges"])
            graph = ReductionGraph(
                node_ids=nodes,
                node_weights=graph_data["node_weights"],
                edges=edges,
                edge_reasons={edge: "persisted first-round edge" for edge in edges},
                graph_policy_id=graph_data["graph_policy_id"],
                graph_policy_version=graph_data["graph_policy_version"],
            )
    return asset_ids, _correlation_matrix(covariance), graph

