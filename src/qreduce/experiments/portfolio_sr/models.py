"""Immutable contracts for the Sharpe ratio portfolio experiment.

This module defines the core data structures:
- ReturnConvention: simple vs logarithmic return calculation
- SectorConstraints: sector-level diversification bounds
- SharpeGraphPolicy: MWIS graph construction policy
- SharpePortfolioProblem: validated input problem with optional cardinality
- TransformedSharpeProblem: reformulated QP ready for classical solver

The transformation follows:
    Original: max SR(x) = (mu^T * x) / sqrt(x^T * Sigma * x)

    Transformed (with x_scale = 1/(mu^T * x)):
        min  x_scaled^T * Sigma * x_scaled
        s.t. mu^T * x_scaled = 1
             sum_i x_scaled_i = x_scale
             0 <= x_scaled_i <= upper_i * x_scale
             sector_min_s * x_scale <= sum_{i in s} x_scaled_i <= sector_max_s * x_scale
             1/mu_max <= x_scale <= 1/mu_min

    Recovery: x_i = x_scaled_i / x_scale, SR = 1/sqrt(objective)
"""

import math
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal

import numpy as np

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


class ReturnConvention(str, Enum):
    """Return calculation convention."""

    SIMPLE = "simple"
    LOG = "log"


# Type alias for edge mode
EdgeMode = Literal["correlation_only", "near_duplicate"]


@dataclass(frozen=True, slots=True)
class SectorConstraints:
    """Sector diversification constraints.

    Each sector can have minimum and maximum exposure limits.
    These are hard constraints in the final optimization, not MWIS penalties.
    """

    sector_min: Mapping[str, float]
    sector_max: Mapping[str, float]

    def __post_init__(self) -> None:
        min_sectors = set(self.sector_min.keys())
        max_sectors = set(self.sector_max.keys())
        if min_sectors != max_sectors:
            raise ValueError("sector_min and sector_max must have identical keys.")

        for sector in min_sectors:
            min_val = self.sector_min[sector]
            max_val = self.sector_max[sector]

            if not math.isfinite(min_val) or min_val < 0:
                raise ValueError(f"sector_min[{sector}] must be finite and non-negative.")
            if not math.isfinite(max_val) or max_val < 0:
                raise ValueError(f"sector_max[{sector}] must be finite and non-negative.")
            if min_val > max_val:
                raise ValueError(f"sector_min[{sector}] cannot exceed sector_max[{sector}].")
            if max_val > 1:
                raise ValueError(f"sector_max[{sector}] cannot exceed 1.")

        # Validate total minimums don't exceed budget
        total_min = sum(self.sector_min.values())
        if total_min > 1 + 1e-9:
            raise ValueError(f"Sum of sector minimums ({total_min:.6g}) exceeds budget of 1.")

        # Freeze mappings
        object.__setattr__(self, "sector_min", MappingProxyType(dict(self.sector_min)))
        object.__setattr__(self, "sector_max", MappingProxyType(dict(self.sector_max)))

    @property
    def sectors(self) -> frozenset[str]:
        """Set of sector names."""
        return frozenset(self.sector_min.keys())

    def to_dict(self) -> dict[str, object]:
        """Serialize for artifact storage."""
        return {
            "sector_min": dict(self.sector_min),
            "sector_max": dict(self.sector_max),
        }


@dataclass(frozen=True, slots=True)
class SharpeGraphPolicy:
    """MWIS graph construction policy for Sharpe portfolio.

    Edges represent potential redundancy between assets:
    - correlation_only: edge if |corr(i,j)| >= threshold
    - near_duplicate: edge if correlation AND similar return/variance

    Node weights are individual Sharpe ratios (mu_i / sigma_i), normalized.
    """

    policy_id: str
    policy_version: str
    correlation_threshold: float
    edge_mode: EdgeMode = "near_duplicate"
    near_duplicate_max_return_diff: float | None = 0.10
    near_duplicate_max_variance_diff: float | None = 0.10
    node_weight_policy_id: str = "individual_sharpe_ratio"
    node_weight_normalization: str = "divide_by_max"

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("Policy ID and version cannot be blank.")

        if self.edge_mode not in ("correlation_only", "near_duplicate"):
            raise ValueError("edge_mode must be 'correlation_only' or 'near_duplicate'.")

        if not math.isfinite(self.correlation_threshold) or not 0 <= self.correlation_threshold <= 1:
            raise ValueError("correlation_threshold must be in [0, 1].")

        if self.edge_mode == "near_duplicate":
            if self.near_duplicate_max_return_diff is None:
                raise ValueError("near_duplicate_max_return_diff required for near_duplicate mode.")
            if self.near_duplicate_max_variance_diff is None:
                raise ValueError("near_duplicate_max_variance_diff required for near_duplicate mode.")
            if not math.isfinite(self.near_duplicate_max_return_diff) or self.near_duplicate_max_return_diff < 0:
                raise ValueError("near_duplicate_max_return_diff must be finite and non-negative.")
            if not math.isfinite(self.near_duplicate_max_variance_diff) or self.near_duplicate_max_variance_diff < 0:
                raise ValueError("near_duplicate_max_variance_diff must be finite and non-negative.")

    def to_dict(self) -> dict[str, object]:
        """Serialize for artifact storage."""
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class SharpePortfolioProblem:
    """Validated Sharpe ratio optimization problem.

    Long-only portfolio with:
    - Continuous weights
    - Unit budget constraint
    - Optional upper bounds per asset
    - Optional sector constraints
    - Optional lower bounds conditional on selection
    - Optional minimum and maximum binary selection counts

    All tickers must have strictly positive mean returns.
    """

    tickers: tuple[str, ...]
    mean_returns: Mapping[str, float]
    covariance: tuple[tuple[float, ...], ...]
    sectors: Mapping[str, str]
    upper_bounds: Mapping[str, float]
    sector_constraints: SectorConstraints | None = None
    max_positions: int | None = None
    risk_free_rate: float = 0.0
    covariance_symmetry_tolerance: float = 1e-12
    lower_bound: float = field(default=0.0, kw_only=True, metadata={"omit_if_default": True})
    lower_bounds: Mapping[str, float] | None = field(
        default=None, kw_only=True, metadata={"omit_if_none": True}
    )
    min_selected_assets: int | None = field(
        default=None, kw_only=True, metadata={"omit_if_none": True}
    )
    _covariance_validated: InitVar[bool] = False

    def __post_init__(self, _covariance_validated: bool) -> None:
        tickers = tuple(self.tickers)
        n = len(tickers)

        if n == 0 or any(not t.strip() for t in tickers):
            raise ValueError("tickers must be non-empty with non-blank values.")
        if len(set(tickers)) != n:
            raise ValueError("tickers must be unique.")

        # Validate mean returns
        _freeze_ticker_mapping(self, "mean_returns", self.mean_returns, tickers, allow_nonpositive=False)

        # Validate sectors
        _freeze_ticker_mapping(self, "sectors", self.sectors, tickers, string_values=True)

        # Validate upper bounds
        _freeze_ticker_mapping(self, "upper_bounds", self.upper_bounds, tickers)
        if any(upper < 0 for upper in self.upper_bounds.values()):
            raise ValueError("upper_bounds must be non-negative.")

        if not math.isfinite(self.lower_bound) or not 0 <= self.lower_bound <= 1:
            raise ValueError("lower_bound must be finite and between 0 and 1.")
        if self.lower_bounds is not None:
            if self.lower_bound > 0:
                raise ValueError("A positive lower_bound cannot be combined with lower_bounds.")
            if not isinstance(self.lower_bounds, Mapping):
                raise TypeError("lower_bounds must be a mapping or None.")
            floors = dict(self.lower_bounds)
            unknown = set(floors).difference(tickers)
            if unknown:
                raise ValueError(f"lower_bounds contains unknown tickers: {sorted(map(str, unknown))}.")
            for ticker, floor in floors.items():
                if not math.isfinite(floor) or not 0 <= floor <= 1:
                    raise ValueError(f"lower_bounds[{ticker}] must be finite and between 0 and 1.")
            object.__setattr__(
                self, "lower_bounds", MappingProxyType(floors) if any(floors.values()) else None,
            )
        if any(self.effective_lower_bound(t) > self.upper_bounds[t] for t in tickers):
            raise ValueError("Effective lower_bound cannot exceed the corresponding upper bound.")

        # Validate risk-free rate
        # Current version requires risk_free_rate=0.0 because the transformed
        # objective uses raw returns, not excess returns. Non-zero values would
        # create inconsistency between the optimized objective and reported Sharpe.
        if not math.isfinite(self.risk_free_rate):
            raise ValueError("risk_free_rate must be finite.")
        if self.risk_free_rate != 0.0:
            raise ValueError(
                "risk_free_rate must be 0.0 in current version. "
                "Non-zero risk-free rate requires coordinated changes to "
                "return filtering, normalization, scale bounds, and metrics."
            )

        # Validate max_positions
        if self.max_positions is not None:
            if isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int):
                raise TypeError("max_positions must be an integer or None.")
            if self.max_positions < 1:
                raise ValueError("max_positions must be at least 1.")
            if self.max_positions > n:
                raise ValueError(f"max_positions ({self.max_positions}) cannot exceed ticker count ({n}).")

        minimum = self.min_selected_assets
        if minimum is not None:
            if isinstance(minimum, bool) or not isinstance(minimum, int):
                raise TypeError("min_selected_assets must be an integer or None.")
            if not 0 <= minimum <= n:
                raise ValueError(f"min_selected_assets must be between 0 and ticker count ({n}).")
            if self.max_positions is not None and minimum > self.max_positions:
                raise ValueError("min_selected_assets cannot exceed max_positions.")
            if minimum == 0:
                object.__setattr__(self, "min_selected_assets", None)

        # Validate covariance
        covariance = tuple(tuple(row) for row in self.covariance)
        if len(covariance) != n or any(len(row) != n for row in covariance):
            raise ValueError("covariance must be a square matrix aligned with tickers.")

        tol = self.covariance_symmetry_tolerance
        for i, row in enumerate(covariance):
            for j, val in enumerate(row):
                if not math.isfinite(val):
                    raise ValueError(f"covariance[{i}][{j}] must be finite.")
                if abs(val - covariance[j][i]) > tol:
                    raise ValueError("covariance must be symmetric.")
            if row[i] <= 0:
                raise ValueError(f"covariance diagonal [{i}] must be positive.")

        # Check PSD if not already validated
        if not _covariance_validated:
            matrix = np.asarray(covariance, dtype=float)
            matrix = 0.5 * (matrix + matrix.T)
            try:
                np.linalg.cholesky(matrix + 1e-10 * np.eye(n))
            except np.linalg.LinAlgError as e:
                raise ValueError("covariance must be positive semi-definite.") from e

        # Validate sector constraints cover all sectors in the problem
        if self.sector_constraints is not None:
            problem_sectors = set(self.sectors.values())
            constraint_sectors = self.sector_constraints.sectors
            if problem_sectors != constraint_sectors:
                missing = problem_sectors - constraint_sectors
                extra = constraint_sectors - problem_sectors
                raise ValueError(
                    f"sector_constraints mismatch. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
                )

        # Keep the legacy maximum-cardinality diagnostic; the budget also
        # applies to problems without selection binaries.
        sorted_uppers = sorted(self.upper_bounds.values(), reverse=True)
        capacity = sum(sorted_uppers[:self.max_positions])
        if self.max_positions is not None:
            if capacity < 1 - tol:
                raise ValueError(
                    f"Upper bounds of top {self.max_positions} assets sum to {capacity:.6g}, "
                    "cannot satisfy unit budget."
                )
        elif capacity < 1 - tol:
            raise ValueError(f"insufficient_budget_capacity:{capacity:.6g}")

        object.__setattr__(self, "tickers", tickers)
        object.__setattr__(self, "covariance", covariance)
        if self.lower_bound > 0 or self.lower_bounds is not None or self.min_selected_assets:
            issues = self.selection_feasibility_issues(tickers)
            if issues:
                raise ValueError("; ".join(issues))

    @property
    def has_selection_binaries(self) -> bool:
        """Every asset has a selection variable, including in baseline models."""
        return True

    def effective_lower_bound(self, ticker: str) -> float:
        """Return the investment floor for a selected ticker."""
        return self.lower_bounds.get(ticker, self.lower_bound) if self.lower_bounds else self.lower_bound

    def selection_feasibility_issues(self, tickers: tuple[str, ...]) -> tuple[str, ...]:
        """Necessary budget and sector checks for a candidate universe."""
        issues = []
        minimum = self.min_selected_assets or 0
        eligible = tickers
        if self.sector_constraints:
            sector_max = self.sector_constraints.sector_max
            eligible = tuple(
                t for t in tickers if self.effective_lower_bound(t) <= sector_max[self.sectors[t]] + 1e-9
            )
            eligible_sectors = {self.sectors[t] for t in eligible}
            for sector in sorted(self.sector_constraints.sectors - eligible_sectors):
                if self.sector_constraints.sector_min[sector] > 0:
                    issues.append(f"sector_max_below_lower_bound:{sector}")

        if len(eligible) < minimum:
            issues.append(f"insufficient_selection_candidates:{len(eligible)}<min={minimum}")
        limit = min(len(eligible), self.max_positions or len(eligible))
        budget_with_tolerance = 1 + 1e-9
        floor_sum = 0.0
        cheapest_floors = sorted(self.effective_lower_bound(t) for t in eligible)[:limit]
        for count, floor in enumerate(cheapest_floors):
            floor_sum += floor
            if floor_sum > budget_with_tolerance:
                limit = count
                if limit < minimum:
                    issues.append(f"minimum_selection_floors_exceed_budget:min={minimum}")
                break
        capacity = sum(sorted((self.upper_bounds[t] for t in eligible), reverse=True)[:limit])
        if capacity < 1 - 1e-9:
            issues.append(f"insufficient_budget_capacity:{capacity:.6g}")
        return tuple(issues)

    @property
    def ticker_count(self) -> int:
        """Number of assets in the problem."""
        return len(self.tickers)

    def ticker_index(self, ticker: str) -> int:
        """Return the matrix index for a ticker."""
        return self.tickers.index(ticker)

    def variance(self, ticker: str) -> float:
        """Return the variance for a ticker."""
        i = self.ticker_index(ticker)
        return self.covariance[i][i]

    def correlation(self, ticker_a: str, ticker_b: str) -> float:
        """Return the correlation between two tickers."""
        i = self.ticker_index(ticker_a)
        j = self.ticker_index(ticker_b)
        return self.covariance[i][j] / math.sqrt(self.covariance[i][i] * self.covariance[j][j])

    def sharpe_ratio(self, ticker: str) -> float:
        """Return the individual Sharpe ratio for a ticker."""
        mu = self.mean_returns[ticker] - self.risk_free_rate
        sigma = math.sqrt(self.variance(ticker))
        return mu / sigma if sigma > 0 else 0.0

    def tickers_in_sector(self, sector: str) -> tuple[str, ...]:
        """Return tickers in the specified sector."""
        return tuple(t for t in self.tickers if self.sectors[t] == sector)

    @property
    def mu_min(self) -> float:
        """Minimum mean return across all tickers."""
        return min(self.mean_returns.values())

    @property
    def mu_max(self) -> float:
        """Maximum mean return across all tickers."""
        return max(self.mean_returns.values())

    @property
    def x_scale_bounds(self) -> tuple[float, float]:
        """Valid range for x_scale variable: (1/mu_max, 1/mu_min)."""
        return (1 / self.mu_max, 1 / self.mu_min)

    def to_dict(self) -> dict[str, object]:
        """Serialize for artifact storage."""
        result = {
            "tickers": list(self.tickers),
            "ticker_count": self.ticker_count,
            "sectors": dict(self.sectors),
            "sector_count": len(set(self.sectors.values())),
            "max_positions": self.max_positions,
            "risk_free_rate": self.risk_free_rate,
            "mu_range": {"min": self.mu_min, "max": self.mu_max},
            "x_scale_bounds": {"lower": self.x_scale_bounds[0], "upper": self.x_scale_bounds[1]},
            "sector_constraints": self.sector_constraints.to_dict() if self.sector_constraints else None,
        }
        if self.lower_bound > 0:
            result["lower_bound"] = self.lower_bound
        if self.lower_bounds is not None:
            result["lower_bounds"] = dict(self.lower_bounds)
        if self.min_selected_assets is not None:
            result["min_selected_assets"] = self.min_selected_assets
        return result


@dataclass(frozen=True, slots=True)
class SharpeVariableMapping:
    """Stable mapping from tickers to optimization variable names."""

    x_scaled_by_ticker: Mapping[str, str]
    delta_by_ticker: Mapping[str, str] | None  # None allowed for historical mappings only
    x_scale_variable: str = "x_scale"

    def __post_init__(self) -> None:
        x_mapping = dict(self.x_scaled_by_ticker)
        if any(not t.strip() or not v.strip() for t, v in x_mapping.items()):
            raise ValueError("Variable names must be non-blank.")

        all_names = set(x_mapping.values()) | {self.x_scale_variable}

        if self.delta_by_ticker is not None:
            delta_mapping = dict(self.delta_by_ticker)
            if set(delta_mapping.keys()) != set(x_mapping.keys()):
                raise ValueError("Delta and x_scaled mappings must cover the same tickers.")
            all_names |= set(delta_mapping.values())
            object.__setattr__(self, "delta_by_ticker", MappingProxyType(delta_mapping))

        if len(all_names) != len(set(x_mapping.values())) + 1 + (
            len(self.delta_by_ticker) if self.delta_by_ticker else 0
        ):
            raise ValueError("Variable names must be globally unique.")

        object.__setattr__(self, "x_scaled_by_ticker", MappingProxyType(x_mapping))

    @classmethod
    def for_problem(cls, problem: SharpePortfolioProblem) -> "SharpeVariableMapping":
        """Create standard variable mapping for a problem."""
        x_scaled = {t: f"x_scaled__{t}" for t in problem.tickers}
        delta = {t: f"delta__{t}" for t in problem.tickers}
        return cls(x_scaled_by_ticker=x_scaled, delta_by_ticker=delta)

    def require_deltas(self) -> Mapping[str, str]:
        """Require selection variables when using a mapping in a new model."""
        if self.delta_by_ticker is None:
            raise ValueError("Selection binary mapping is required for a new model.")
        return self.delta_by_ticker


@dataclass(frozen=True, slots=True)
class TransformedSharpeProblem:
    """Reformulated Sharpe optimization ready for classical solver.

    The transformation converts:
        max mu^T x / sqrt(x^T Sigma x)

    To the mixed-integer quadratic model:
        min x_scaled^T Sigma x_scaled
        s.t. mu^T x_scaled = 1
             constraints on x_scaled, x_scale and binary selections

    Solution recovery: x = x_scaled / x_scale, SR = 1/sqrt(objective)
    """

    original_problem: SharpePortfolioProblem
    retained_tickers: tuple[str, ...]
    fixing_manifest: FixingManifest
    variable_mapping: SharpeVariableMapping

    def __post_init__(self) -> None:
        retained = tuple(self.retained_tickers)
        original_tickers = set(self.original_problem.tickers)

        if len(set(retained)) != len(retained):
            raise ValueError("retained_tickers must be unique.")
        if set(retained) - original_tickers:
            raise ValueError("retained_tickers must be subset of original tickers.")
        if set(retained) != set(self.fixing_manifest.retained_item_ids):
            raise ValueError("retained_tickers must match fixing manifest.")
        if (set(self.variable_mapping.x_scaled_by_ticker) != original_tickers
                or self.variable_mapping.delta_by_ticker is None
                or set(self.variable_mapping.delta_by_ticker) != original_tickers):
            raise ValueError("Variable mapping must cover every ticker with weights and binaries.")

        if set(self.fixing_manifest.excluded_item_ids) != original_tickers - set(retained):
            raise ValueError("Fixing manifest must exclude exactly the non-retained tickers.")
        deltas = self.variable_mapping.require_deltas()
        for entry in self.fixing_manifest.entries:
            expected = {self.variable_mapping.x_scaled_by_ticker[entry.item_id]: 0.0,
                        deltas[entry.item_id]: 0.0}
            if entry.variable_values != expected:
                raise ValueError(
                    f"Fixing for {entry.item_id} must set exactly its scaled weight and selection binary to zero."
                )

        object.__setattr__(self, "retained_tickers", retained)

    @property
    def variable_count(self) -> int:
        """Total number of optimization variables."""
        return 2 * len(self.original_problem.tickers) + 1

    @property
    def constraint_count(self) -> int:
        """Count the compiled linear rows without constructing the quadratic objective."""
        return len(self._build_linear_constraints())

    def build_classical_model(self) -> ClassicalOptimizationModel:
        """Compile to solver-agnostic optimization model."""
        problem = self.original_problem
        mapping = self.variable_mapping
        deltas = mapping.require_deltas()
        tickers = problem.tickers

        # Variables
        variables: list[ClassicalVariable] = []

        # x_scaled variables (continuous, non-negative)
        for ticker in tickers:
            variables.append(ClassicalVariable(
                mapping.x_scaled_by_ticker[ticker],
                ClassicalVariableType.CONTINUOUS,
                0.0,
                None,
            ))

        # x_scale variable (continuous, bounded)
        lb, ub = problem.x_scale_bounds
        variables.append(ClassicalVariable(
            mapping.x_scale_variable,
            ClassicalVariableType.CONTINUOUS,
            lb,
            ub,
        ))

        # Selection binaries are present even without cardinality or floors.
        for ticker in tickers:
            variables.append(ClassicalVariable(
                deltas[ticker], ClassicalVariableType.BINARY, 0.0, 1.0,
            ))

        # Quadratic objective: x_scaled^T Sigma x_scaled
        quadratic_terms: list[QuadraticObjectiveTerm] = []
        for i, ticker_i in enumerate(tickers):
            for j, ticker_j in enumerate(tickers[i:], start=i):
                coef = problem.covariance[i][j]
                if i != j:
                    coef *= 2  # Off-diagonal terms counted once
                quadratic_terms.append(QuadraticObjectiveTerm(
                    mapping.x_scaled_by_ticker[ticker_i],
                    mapping.x_scaled_by_ticker[ticker_j],
                    coef,
                ))

        return ClassicalOptimizationModel(
            variables=tuple(variables),
            linear_objective={},  # No linear objective terms
            quadratic_objective=tuple(quadratic_terms),
            linear_constraints=self._build_linear_constraints(),
        )

    def _build_linear_constraints(self) -> tuple[LinearConstraint, ...]:
        problem = self.original_problem
        mapping = self.variable_mapping
        deltas = mapping.require_deltas()
        tickers = problem.tickers
        _, ub = problem.x_scale_bounds
        constraints: list[LinearConstraint] = []

        # mu^T x_scaled = 1
        constraints.append(LinearConstraint(
            "return_normalization",
            {mapping.x_scaled_by_ticker[t]: problem.mean_returns[t] for t in tickers},
            LinearConstraintSense.EQUAL,
            1.0,
        ))

        # sum_i x_scaled_i = x_scale
        budget_coeffs = {mapping.x_scaled_by_ticker[t]: 1.0 for t in tickers}
        budget_coeffs[mapping.x_scale_variable] = -1.0
        constraints.append(LinearConstraint(
            "budget_scale_link",
            budget_coeffs,
            LinearConstraintSense.EQUAL,
            0.0,
        ))

        # Upper bounds: x_scaled_i <= upper_i * x_scale
        for ticker in tickers:
            coeffs = {
                mapping.x_scaled_by_ticker[ticker]: 1.0,
                mapping.x_scale_variable: -problem.upper_bounds[ticker],
            }
            constraints.append(LinearConstraint(
                f"upper_bound__{ticker}",
                coeffs,
                LinearConstraintSense.LESS_EQUAL,
                0.0,
            ))

        # Lower bound (non-negativity is handled by variable bounds)
        # x_scaled_i >= 0 is implicit

        if problem.min_selected_assets is not None:
            constraints.append(LinearConstraint(
                "min_cardinality",
                {deltas[t]: 1.0 for t in tickers},
                LinearConstraintSense.GREATER_EQUAL,
                float(problem.min_selected_assets),
            ))

        # Cardinality constraint: sum_i delta_i <= max_positions
        if problem.max_positions is not None:
            constraints.append(LinearConstraint(
                "max_cardinality",
                {deltas[t]: 1.0 for t in tickers},
                LinearConstraintSense.LESS_EQUAL,
                float(problem.max_positions),
            ))

        # Linking: x_scaled_i <= M_i * delta_i where M_i = upper_i / mu_min
        for ticker in tickers:
            M_i = problem.upper_bounds[ticker] / problem.mu_min
            coeffs = {
                mapping.x_scaled_by_ticker[ticker]: 1.0,
                deltas[ticker]: -M_i,
            }
            constraints.append(LinearConstraint(
                f"cardinality_link__{ticker}", coeffs,
                LinearConstraintSense.LESS_EQUAL, 0.0,
            ))
            floor = problem.effective_lower_bound(ticker)
            if floor > 0:
                big_m = floor * ub
                constraints.append(LinearConstraint(
                    f"lower_bound__{ticker}",
                    {mapping.x_scaled_by_ticker[ticker]: 1.0,
                     mapping.x_scale_variable: -floor,
                     deltas[ticker]: -big_m},
                    LinearConstraintSense.GREATER_EQUAL,
                    -big_m,
                ))

        # Sector constraints
        if problem.sector_constraints:
            for sector in problem.sector_constraints.sectors:
                sector_tickers = problem.tickers_in_sector(sector)
                if not sector_tickers:
                    continue

                min_val = problem.sector_constraints.sector_min[sector]
                max_val = problem.sector_constraints.sector_max[sector]

                # sum_{i in sector} x_scaled_i >= min * x_scale
                if min_val > 0:
                    coeffs = {mapping.x_scaled_by_ticker[t]: 1.0 for t in sector_tickers}
                    coeffs[mapping.x_scale_variable] = -min_val
                    constraints.append(LinearConstraint(
                        f"sector_min__{sector}",
                        coeffs,
                        LinearConstraintSense.GREATER_EQUAL,
                        0.0,
                    ))

                # sum_{i in sector} x_scaled_i <= max * x_scale
                if max_val < 1:
                    coeffs = {mapping.x_scaled_by_ticker[t]: 1.0 for t in sector_tickers}
                    coeffs[mapping.x_scale_variable] = -max_val
                    constraints.append(LinearConstraint(
                        f"sector_max__{sector}",
                        coeffs,
                        LinearConstraintSense.LESS_EQUAL,
                        0.0,
                    ))

        # Fixing constraints from manifest
        for entry in self.fixing_manifest.entries:
            for var_name, value in entry.variable_values.items():
                constraints.append(LinearConstraint(
                    f"fix__{entry.item_id}__{var_name}",
                    {var_name: 1.0},
                    LinearConstraintSense.EQUAL,
                    value,
                ))

        return tuple(constraints)

    def to_dict(self) -> dict[str, object]:
        """Serialize for artifact storage."""
        return {
            "original_problem": self.original_problem.to_dict(),
            "retained_tickers": list(self.retained_tickers),
            "retained_count": len(self.retained_tickers),
            "variable_count": self.variable_count,
            "constraint_count": self.constraint_count,
        }


def _freeze_ticker_mapping(
    instance: object,
    attr_name: str,
    mapping: Mapping[str, object],
    tickers: tuple[str, ...],
    *,
    allow_nonpositive: bool = True,
    string_values: bool = False,
) -> None:
    """Validate and freeze a ticker-indexed mapping."""
    values = dict(mapping)

    if set(values.keys()) != set(tickers):
        raise ValueError(f"{attr_name} keys must exactly match tickers.")

    for ticker, value in values.items():
        if string_values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{attr_name}[{ticker}] must be non-blank string.")
        else:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{attr_name}[{ticker}] must be finite number.")
            if not allow_nonpositive and value <= 0:
                raise ValueError(f"{attr_name}[{ticker}] must be positive.")

    object.__setattr__(instance, attr_name, MappingProxyType(values))
