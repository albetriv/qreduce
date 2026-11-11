"""Immutable contracts for the synthetic portfolio experiment."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.domains.contracts import FixingManifest
from qreduce.solving.residual import (
    ClassicalOptimizationModel,
    ClassicalVariable,
    ClassicalVariableType,
    LinearConstraint,
    LinearConstraintSense,
    QuadraticObjectiveTerm,
)


@dataclass(frozen=True, slots=True)
class PortfolioGraphPolicy:
    """Versioned, explicit graph policy for the portfolio experiment."""

    policy_id: str
    policy_version: str
    correlation_absolute_threshold: float
    weight_formula_description: str = "node_weight = retention_score"
    weight_normalization: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("Portfolio graph policy ID and version cannot be blank.")
        if not math.isfinite(self.correlation_absolute_threshold) or not 0 <= self.correlation_absolute_threshold <= 1:
            raise ValueError("correlation_absolute_threshold must be finite and in [0, 1].")
        if not self.weight_formula_description.strip():
            raise ValueError("weight_formula_description cannot be blank.")


@dataclass(frozen=True, slots=True)
class PortfolioProblem:
    """Validated mean-variance MIQP data with stable asset IDs."""

    asset_ids: tuple[str, ...]
    expected_returns: Mapping[str, float]
    covariance: tuple[tuple[float, ...], ...]
    lower_bounds: Mapping[str, float]
    upper_bounds: Mapping[str, float]
    retention_scores: Mapping[str, float]
    risk_aversion: float
    covariance_symmetry_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        asset_ids = tuple(self.asset_ids)
        if not asset_ids or any(not asset_id.strip() for asset_id in asset_ids) or len(set(asset_ids)) != len(asset_ids):
            raise ValueError("asset_ids must be non-empty, non-blank and unique.")
        _freeze_asset_mapping(self, "expected_returns", self.expected_returns, asset_ids, allow_negative=True)
        _freeze_asset_mapping(self, "lower_bounds", self.lower_bounds, asset_ids, allow_negative=False)
        _freeze_asset_mapping(self, "upper_bounds", self.upper_bounds, asset_ids, allow_negative=False)
        _freeze_asset_mapping(self, "retention_scores", self.retention_scores, asset_ids, allow_negative=False)
        if not math.isfinite(self.risk_aversion) or self.risk_aversion <= 0:
            raise ValueError("risk_aversion must be finite and greater than zero.")
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
        lower_bounds = self.lower_bounds
        upper_bounds = self.upper_bounds
        if any(lower_bounds[asset_id] > upper_bounds[asset_id] for asset_id in asset_ids):
            raise ValueError("Each lower bound must not exceed its upper bound.")
        if sum(lower_bounds.values()) > 1 + self.covariance_symmetry_tolerance:
            raise ValueError("Lower bounds make the unit budget infeasible.")
        if sum(upper_bounds.values()) < 1 - self.covariance_symmetry_tolerance:
            raise ValueError("Upper bounds cannot satisfy the unit budget.")
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
        return 1 + 2 * len(self.original_problem.asset_ids) + 2 * len(self.fixing_manifest.entries)

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