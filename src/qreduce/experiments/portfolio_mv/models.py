"""Immutable contracts for the synthetic portfolio experiment."""

import math
from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from types import MappingProxyType
from typing import Literal

import numpy as np

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.domains.contracts import FixingManifest
from qreduce.experiments.portfolio_mv.validation import validate_risk_aversion
from qreduce.solving.residual import (
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
    QuadraticObjectiveTerm,
)

# Type alias for edge mode
EdgeMode = Literal["correlation_only", "near_duplicate"]


@dataclass(frozen=True, slots=True)
class SyntheticPortfolioGenerationPolicy:
    """Versioned, explicit generation policy for synthetic portfolio data.

    This policy defines a factorial model for generating synthetic historical returns:
        R[t, i] = alpha_i + beta_market_i * market_factor[t]
                  + beta_cluster_i * cluster_factor[cluster(i), t]
                  + idiosyncratic_return[t, i]

    From the generated returns matrix, the following are derived deterministically:
        - expected_returns: mean_t(R[t, i])
        - covariance: sample covariance matrix
        - retention_scores: max(expected_return_i, 0) / variance_i, normalized
    """

    policy_id: str
    policy_version: str
    random_seed: int
    observation_count: int
    asset_count: int
    cluster_count: int
    market_factor_volatility: float
    cluster_factor_volatility: float
    idiosyncratic_volatility: float
    # Alpha (intercept) parameters: alpha_i = alpha_base + alpha_spread * (i / (n-1))
    alpha_base: float = 0.05
    alpha_spread: float = 0.10
    # Beta market parameters: beta_market_i = beta_market_base + beta_market_spread * (i / (n-1))
    beta_market_base: float = 0.8
    beta_market_spread: float = 0.4
    # Beta cluster parameters: beta_cluster_i = beta_cluster_base + beta_cluster_spread * (i % cluster_count / (cluster_count-1))
    beta_cluster_base: float = 0.3
    beta_cluster_spread: float = 0.4
    # Minimum observations required relative to asset count
    min_observations_per_asset: int = 10

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("Generation policy ID and version cannot be blank.")
        if not isinstance(self.random_seed, int):
            raise TypeError("random_seed must be an integer.")
        if self.asset_count < 2:
            raise ValueError("asset_count must be at least 2.")
        if self.cluster_count < 1:
            raise ValueError("cluster_count must be at least 1.")
        if self.cluster_count > self.asset_count:
            raise ValueError("cluster_count cannot exceed asset_count.")
        if self.observation_count < self.asset_count * self.min_observations_per_asset:
            raise ValueError(
                f"observation_count must be at least {self.min_observations_per_asset} * asset_count "
                f"({self.asset_count * self.min_observations_per_asset})."
            )
        for name, value in [
            ("market_factor_volatility", self.market_factor_volatility),
            ("cluster_factor_volatility", self.cluster_factor_volatility),
            ("idiosyncratic_volatility", self.idiosyncratic_volatility),
        ]:
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        for name, value in [
            ("alpha_base", self.alpha_base),
            ("alpha_spread", self.alpha_spread),
            ("beta_market_base", self.beta_market_base),
            ("beta_market_spread", self.beta_market_spread),
            ("beta_cluster_base", self.beta_cluster_base),
            ("beta_cluster_spread", self.beta_cluster_spread),
        ]:
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PortfolioGraphPolicy:
    """Versioned, explicit graph policy for the portfolio experiment.

    Supports two edge modes:
    - correlation_only: edge(i,j) if abs(correlation_ij) >= threshold
    - near_duplicate: edge(i,j) if correlation AND relative return/variance differences are small
    """

    policy_id: str
    policy_version: str
    correlation_absolute_threshold: float
    edge_mode: EdgeMode = "near_duplicate"
    # Near-duplicate mode parameters (required when edge_mode="near_duplicate")
    near_duplicate_max_relative_return_difference: float | None = 0.10
    near_duplicate_max_relative_variance_difference: float | None = 0.10
    # Node weight policy metadata
    node_weight_policy_id: str = "mean_variance_return_over_variance"
    node_weight_policy_version: str = "1"
    node_weight_formula_description: str = "max(expected_return_i, 0) / covariance_ii, normalized by global maximum"
    node_weight_normalization: str = "divide_by_max"

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("Portfolio graph policy ID and version cannot be blank.")
        if self.edge_mode not in ("correlation_only", "near_duplicate"):
            raise ValueError(f"edge_mode must be 'correlation_only' or 'near_duplicate', got '{self.edge_mode}'.")
        if not math.isfinite(self.correlation_absolute_threshold) or not 0 <= self.correlation_absolute_threshold <= 1:
            raise ValueError("correlation_absolute_threshold must be finite and in [0, 1].")
        if self.edge_mode == "near_duplicate":
            if self.near_duplicate_max_relative_return_difference is None:
                raise ValueError("near_duplicate_max_relative_return_difference is required when edge_mode='near_duplicate'.")
            if self.near_duplicate_max_relative_variance_difference is None:
                raise ValueError("near_duplicate_max_relative_variance_difference is required when edge_mode='near_duplicate'.")
            if not math.isfinite(self.near_duplicate_max_relative_return_difference) or self.near_duplicate_max_relative_return_difference < 0:
                raise ValueError("near_duplicate_max_relative_return_difference must be finite and non-negative.")
            if not math.isfinite(self.near_duplicate_max_relative_variance_difference) or self.near_duplicate_max_relative_variance_difference < 0:
                raise ValueError("near_duplicate_max_relative_variance_difference must be finite and non-negative.")
        if not self.node_weight_policy_id.strip() or not self.node_weight_policy_version.strip():
            raise ValueError("node_weight_policy_id and node_weight_policy_version cannot be blank.")
        if not self.node_weight_formula_description.strip():
            raise ValueError("node_weight_formula_description cannot be blank.")

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


_GENERATED_COVARIANCE = object()


@dataclass(frozen=True, slots=True)
class PortfolioProblem:
    """Validated mean-variance data; explicit covariance uses shifted Cholesky.

    The absolute diagonal shift is 1e-8; the Cholesky boundary is strict
    and subject to floating-point rounding. The input matrix is not modified.

    Cardinality constraints (min_selected_assets, max_selected_assets) are optional.
    When set, they constrain the number of assets with delta_i = 1:
        min_selected_assets <= sum_i delta_i <= max_selected_assets

    Lower/upper bounds define conditional investment limits per asset:
        lower_bound_i * delta_i <= x_i <= upper_bound_i * delta_i

    The validation no longer requires the sum of ALL lower bounds to be <= 1,
    since not all assets must be selected. Instead, it validates that:
    - Each lower_bound <= upper_bound
    - Budget feasibility with cardinality constraints when provided
    - Upper bounds can support the minimum cardinality
    - Lower bounds don't make maximum cardinality infeasible
    """

    asset_ids: tuple[str, ...]
    expected_returns: Mapping[str, float]
    covariance: tuple[tuple[float, ...], ...]
    lower_bounds: Mapping[str, float]
    upper_bounds: Mapping[str, float]
    retention_scores: Mapping[str, float]
    risk_aversion: float
    min_selected_assets: int | None = None
    max_selected_assets: int | None = None
    covariance_symmetry_tolerance: float = 1e-12
    _covariance_origin: InitVar[object] = None

    def __post_init__(self, _covariance_origin: object) -> None:
        asset_ids = tuple(self.asset_ids)
        if not asset_ids or any(not asset_id.strip() for asset_id in asset_ids) or len(set(asset_ids)) != len(asset_ids):
            raise ValueError("asset_ids must be non-empty, non-blank and unique.")
        _freeze_asset_mapping(self, "expected_returns", self.expected_returns, asset_ids, allow_negative=True)
        _freeze_asset_mapping(self, "lower_bounds", self.lower_bounds, asset_ids, allow_negative=False)
        _freeze_asset_mapping(self, "upper_bounds", self.upper_bounds, asset_ids, allow_negative=False)
        _freeze_asset_mapping(self, "retention_scores", self.retention_scores, asset_ids, allow_negative=False)
        validate_risk_aversion(self.risk_aversion)
        if not math.isfinite(self.covariance_symmetry_tolerance) or self.covariance_symmetry_tolerance < 0:
            raise ValueError("covariance_symmetry_tolerance must be finite and non-negative.")
        covariance = tuple(tuple(row) for row in self.covariance)
        if len(covariance) != len(asset_ids) or any(len(row) != len(asset_ids) for row in covariance):
            raise ValueError("covariance must be a square matrix aligned with asset_ids.")
        for row_index, row in enumerate(covariance):
            for column_index, value in enumerate(row):
                if not math.isfinite(value):
                    raise ValueError("covariance values must be finite.")
                if abs(value - covariance[column_index][row_index]) > self.covariance_symmetry_tolerance:
                    raise ValueError("covariance must be symmetric within covariance_symmetry_tolerance.")
            if row[row_index] <= 0:
                raise ValueError("covariance diagonal values must be greater than zero.")
        if _covariance_origin is not _GENERATED_COVARIANCE:
            matrix = np.asarray(covariance, dtype=float)
            # Use the symmetric part when the input differs within tolerance.
            matrix = 0.5 * matrix + 0.5 * matrix.T
            try:
                np.linalg.cholesky(matrix + 1e-8 * np.eye(len(asset_ids)))
            except np.linalg.LinAlgError as exc:
                raise ValueError("covariance must be positive semi-definite within tolerance.") from exc
        lower_bounds = self.lower_bounds
        upper_bounds = self.upper_bounds
        if any(lower_bounds[asset_id] > upper_bounds[asset_id] for asset_id in asset_ids):
            raise ValueError("Each lower bound must not exceed its upper bound.")

        # Validate cardinality constraints
        n_assets = len(asset_ids)
        min_selected = self.min_selected_assets
        max_selected = self.max_selected_assets

        if min_selected is not None:
            if isinstance(min_selected, bool) or not isinstance(min_selected, int):
                raise TypeError("min_selected_assets must be an integer or None.")
            if min_selected < 0:
                raise ValueError("min_selected_assets must be non-negative.")
            if min_selected > n_assets:
                raise ValueError(f"min_selected_assets ({min_selected}) cannot exceed asset count ({n_assets}).")

        if max_selected is not None:
            if isinstance(max_selected, bool) or not isinstance(max_selected, int):
                raise TypeError("max_selected_assets must be an integer or None.")
            if max_selected < 1:
                raise ValueError("max_selected_assets must be at least 1.")
            if max_selected > n_assets:
                raise ValueError(f"max_selected_assets ({max_selected}) cannot exceed asset count ({n_assets}).")

        if min_selected is not None and max_selected is not None and min_selected > max_selected:
            raise ValueError(
                f"min_selected_assets ({min_selected}) cannot exceed max_selected_assets ({max_selected})."
            )

        # Validate budget feasibility with cardinality constraints
        # Sort upper bounds descending for capacity checks
        sorted_uppers = sorted(upper_bounds.values(), reverse=True)
        sorted_lowers = sorted(lower_bounds.values())

        tolerance = self.covariance_symmetry_tolerance

        # If max_selected is set, check that the k largest upper bounds can reach budget=1
        effective_max = max_selected if max_selected is not None else n_assets
        if sum(sorted_uppers[:effective_max]) < 1 - tolerance:
            raise ValueError(
                f"Upper bounds of top {effective_max} assets sum to {sum(sorted_uppers[:effective_max]):.6g}, "
                f"which cannot satisfy the unit budget."
            )

        # If min_selected is set, check that selecting min_selected assets is feasible
        # The k smallest lower bounds must not exceed the budget
        effective_min = min_selected if min_selected is not None else 1
        if effective_min > 0 and sum(sorted_lowers[:effective_min]) > 1 + tolerance:
            raise ValueError(
                f"Lower bounds of {effective_min} smallest assets sum to {sum(sorted_lowers[:effective_min]):.6g}, "
                f"making minimum cardinality infeasible."
            )

        object.__setattr__(self, "asset_ids", asset_ids)
        object.__setattr__(self, "covariance", covariance)

    def asset_index(self, asset_id: str) -> int:
        """Return the stable covariance-matrix index for one asset ID."""
        return self.asset_ids.index(asset_id)

    def correlation(self, left_asset_id: str, right_asset_id: str) -> float:
        """Return the covariance-derived correlation for two known assets."""
        left_index = self.asset_index(left_asset_id)
        right_index = self.asset_index(right_asset_id)
        denominator = math.sqrt(self.covariance[left_index][left_index] * self.covariance[right_index][right_index])
        return self.covariance[left_index][right_index] / denominator

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PortfolioVariableMapping:
    """Stable mapping from a portfolio item to residual binary and continuous variables."""

    delta_variable_by_asset: Mapping[str, str]
    x_variable_by_asset: Mapping[str, str]

    def __post_init__(self) -> None:
        delta_mapping = dict(self.delta_variable_by_asset)
        x_mapping = dict(self.x_variable_by_asset)
        if set(delta_mapping) != set(x_mapping):
            raise ValueError("Delta and continuous mappings must cover the same assets.")
        if any(not asset_id.strip() or not variable_name.strip() for asset_id, variable_name in delta_mapping.items()):
            raise ValueError("Delta variable mapping must use non-blank IDs and names.")
        if any(not asset_id.strip() or not variable_name.strip() for asset_id, variable_name in x_mapping.items()):
            raise ValueError("Continuous variable mapping must use non-blank IDs and names.")
        if len(set(delta_mapping.values()) | set(x_mapping.values())) != len(delta_mapping) + len(x_mapping):
            raise ValueError("Every residual variable name must be globally unique.")
        object.__setattr__(self, "delta_variable_by_asset", MappingProxyType(delta_mapping))
        object.__setattr__(self, "x_variable_by_asset", MappingProxyType(x_mapping))

    @classmethod
    def for_problem(cls, problem: PortfolioProblem) -> "PortfolioVariableMapping":
        return cls(
            delta_variable_by_asset={asset_id: f"delta__{asset_id}" for asset_id in problem.asset_ids},
            x_variable_by_asset={asset_id: f"x__{asset_id}" for asset_id in problem.asset_ids},
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PortfolioResidualProblem:
    """Opaque-to-core residual portfolio problem ready for a classical backend."""

    original_problem: PortfolioProblem
    retained_item_ids: tuple[str, ...]
    fixing_manifest: FixingManifest
    variable_mapping: PortfolioVariableMapping
    objective_description: str = "risk_aversion * x^T * covariance * x - expected_returns^T * x"
    global_constraint_descriptions: tuple[str, ...] = ("sum_i x_i = 1",)

    def __post_init__(self) -> None:
        retained = tuple(self.retained_item_ids)
        asset_set = set(self.original_problem.asset_ids)
        if len(set(retained)) != len(retained) or set(retained) - asset_set:
            raise ValueError("retained_item_ids must be unique known assets.")
        if set(retained) != set(self.fixing_manifest.retained_item_ids):
            raise ValueError("Residual retained items must match the fixing manifest.")
        if set(self.fixing_manifest.excluded_item_ids) != asset_set - set(retained):
            raise ValueError("Fixing manifest must exclude every and only non-retained asset.")
        if set(self.variable_mapping.delta_variable_by_asset) != asset_set:
            raise ValueError("Variable mapping must cover every portfolio asset.")
        object.__setattr__(self, "retained_item_ids", retained)
        object.__setattr__(self, "global_constraint_descriptions", tuple(self.global_constraint_descriptions))

    @property
    def variable_count(self) -> int:
        return 2 * len(self.original_problem.asset_ids)

    @property
    def constraint_count(self) -> int:
        base_count = 1 + 2 * len(self.original_problem.asset_ids) + 2 * len(self.fixing_manifest.entries)
        cardinality_count = 0
        if self.original_problem.min_selected_assets is not None:
            cardinality_count += 1
        if self.original_problem.max_selected_assets is not None:
            cardinality_count += 1
        return base_count + cardinality_count

    def build_classical_model(self) -> ClassicalOptimizationModel:
        """Compile the portfolio residual problem without importing a solver binding."""
        problem = self.original_problem
        mapping = self.variable_mapping
        asset_ids = problem.asset_ids
        delta_variables = tuple(
            ClassicalVariable(
                mapping.delta_variable_by_asset[asset_id],
                ClassicalVariableType.BINARY,
                0.0,
                1.0,
            )
            for asset_id in asset_ids
        )
        x_variables = tuple(
            ClassicalVariable(
                mapping.x_variable_by_asset[asset_id],
                ClassicalVariableType.CONTINUOUS,
                0.0,
                None,
            )
            for asset_id in asset_ids
        )
        constraints: list[LinearConstraint] = [
            LinearConstraint(
                "budget",
                {mapping.x_variable_by_asset[asset_id]: 1.0 for asset_id in asset_ids},
                LinearConstraintSense.EQUAL,
                1.0,
            )
        ]
        for asset_id in asset_ids:
            delta_name = mapping.delta_variable_by_asset[asset_id]
            x_name = mapping.x_variable_by_asset[asset_id]
            constraints.extend(
                (
                    LinearConstraint(
                        f"lower_link__{asset_id}",
                        {x_name: 1.0, delta_name: -problem.lower_bounds[asset_id]},
                        LinearConstraintSense.GREATER_EQUAL,
                        0.0,
                    ),
                    LinearConstraint(
                        f"upper_link__{asset_id}",
                        {x_name: 1.0, delta_name: -problem.upper_bounds[asset_id]},
                        LinearConstraintSense.LESS_EQUAL,
                        0.0,
                    ),
                )
            )
        for entry in self.fixing_manifest.entries:
            constraints.extend(
                LinearConstraint(
                    f"fix__{entry.item_id}__{variable_name}",
                    {variable_name: 1.0},
                    LinearConstraintSense.EQUAL,
                    value,
                )
                for variable_name, value in entry.variable_values.items()
            )
        # Add cardinality constraints if configured
        if problem.min_selected_assets is not None:
            constraints.append(
                LinearConstraint(
                    "min_cardinality",
                    {mapping.delta_variable_by_asset[asset_id]: 1.0 for asset_id in asset_ids},
                    LinearConstraintSense.GREATER_EQUAL,
                    float(problem.min_selected_assets),
                )
            )
        if problem.max_selected_assets is not None:
            constraints.append(
                LinearConstraint(
                    "max_cardinality",
                    {mapping.delta_variable_by_asset[asset_id]: 1.0 for asset_id in asset_ids},
                    LinearConstraintSense.LESS_EQUAL,
                    float(problem.max_selected_assets),
                )
            )
        quadratic_terms = tuple(
            QuadraticObjectiveTerm(
                mapping.x_variable_by_asset[left_asset_id],
                mapping.x_variable_by_asset[right_asset_id],
                problem.risk_aversion
                * problem.covariance[left_index][right_index]
                * (1.0 if left_index == right_index else 2.0),
            )
            for left_index, left_asset_id in enumerate(asset_ids)
            for right_index, right_asset_id in enumerate(asset_ids[left_index:], start=left_index)
        )
        return ClassicalOptimizationModel(
            variables=delta_variables + x_variables,
            linear_objective={
                mapping.x_variable_by_asset[asset_id]: -problem.expected_returns[asset_id]
                for asset_id in asset_ids
            },
            quadratic_objective=quadratic_terms,
            linear_constraints=tuple(constraints),
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def _freeze_asset_mapping(
    instance: object,
    attribute_name: str,
    values: Mapping[str, float],
    asset_ids: tuple[str, ...],
    *,
    allow_negative: bool,
) -> None:
    normalized_values = dict(values)
    if set(normalized_values) != set(asset_ids):
        raise ValueError(f"{attribute_name} keys must exactly match asset_ids.")
    for value in normalized_values.values():
        if not math.isfinite(value) or (not allow_negative and value < 0):
            raise ValueError(f"{attribute_name} values must be finite" + ("." if allow_negative else " and non-negative."))
    object.__setattr__(instance, attribute_name, MappingProxyType(normalized_values))