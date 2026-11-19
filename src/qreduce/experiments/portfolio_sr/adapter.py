"""Sharpe portfolio adapter implementing ReducibleProblemAdapter protocol.

This adapter enables QReduce domain reduction for Sharpe ratio optimization:
- Maps tickers to MWIS nodes
- Builds reduction graph based on correlation and similarity
- Validates candidate domains for budget and sector feasibility
- Creates fixing manifests for excluded tickers
- Validates final solutions through postcheck

Key design decisions:
- Retention = availability for investment, not mandatory allocation
- Excluded ticker: x_scaled = 0 and delta = 0 (if cardinality)
- Sector constraints are checked in domain validation, not graph
- Graph policy determines edge semantics (correlation vs near-duplicate)
"""

from collections.abc import Mapping

from qreduce.domains.contracts import (
    DomainEvaluationMetric,
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    LogicalVariableCounts,
)
from qreduce.experiments.portfolio_sr.graph_policy import build_sharpe_reduction_graph
from qreduce.experiments.portfolio_sr.models import (
    SharpeGraphPolicy,
    SharpePortfolioProblem,
    SharpeVariableMapping,
    TransformedSharpeProblem,
)
from qreduce.experiments.portfolio_sr.postcheck import validate_sharpe_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.mwis import ReductionGraph
from qreduce.solving.residual.contracts import ClassicalSolveResult


class SharpePortfolioAdapter:
    """Adapter for Sharpe portfolio reduction via MWIS.

    Implements the ReducibleProblemAdapter protocol for integration with
    the QReduce pipeline.
    """

    def __init__(self, graph_policy: SharpeGraphPolicy) -> None:
        """Initialize adapter with graph construction policy.

        Args:
            graph_policy: Policy defining edge semantics and thresholds.
        """
        self._graph_policy = graph_policy

    def describe_input(self, problem: SharpePortfolioProblem) -> object:
        """Expose the problem for deterministic run identification.

        Args:
            problem: The Sharpe portfolio problem.

        Returns:
            Problem representation for hashing.
        """
        return problem

    def evaluate_domain_metrics(
        self,
        problem: object,
        classical_result: ClassicalSolveResult,
        postcheck_result: FinalSolutionValidationResult,
    ) -> tuple[DomainEvaluationMetric, ...]:
        """Return domain-specific metrics after solve.

        Computes Sharpe portfolio metrics from the solution.
        Returns empty metrics (with None values) if solution is not reconstructible.

        Args:
            problem: The problem (original or transformed).
            classical_result: Result from classical solver.
            postcheck_result: Validation result.

        Returns:
            Tuple of evaluation metrics with metric_id identifiers.
        """
        import math

        from qreduce.experiments.portfolio_sr.formulation import (
            compute_portfolio_metrics,
            sharpe_from_objective,
        )

        # Need the original problem and solution to compute metrics
        if isinstance(problem, TransformedSharpeProblem):
            original = problem.original_problem
        elif isinstance(problem, SharpePortfolioProblem):
            original = problem
        else:
            return ()

        # Get variable values from classical result
        if classical_result.variable_values is None:
            return self._empty_metrics()

        # Extract x_scale and validate
        mapping = SharpeVariableMapping.for_problem(original)
        x_scale = classical_result.variable_values.get(mapping.x_scale_variable)

        # x_scale must be present, finite, and positive
        if x_scale is None or not math.isfinite(x_scale) or x_scale <= 0:
            return self._empty_metrics()

        # Reconstruct original weights with validation
        original_weights: dict[str, float] = {}
        for ticker in original.tickers:
            scaled_var = mapping.x_scaled_by_ticker[ticker]
            scaled_weight = classical_result.variable_values.get(scaled_var)

            # All variables must be present and finite
            if scaled_weight is None or not math.isfinite(scaled_weight):
                return self._empty_metrics()

            original_weights[ticker] = scaled_weight / x_scale

        # Compute metrics
        tol = 1e-9
        try:
            metrics = compute_portfolio_metrics(original, original_weights, weight_tolerance=tol)
        except (ValueError, ZeroDivisionError, ArithmeticError):
            return self._empty_metrics()

        # Get objective and Sharpe
        objective = postcheck_result.objective_recomputed
        if objective is not None and math.isfinite(objective) and objective > 0:
            sharpe = sharpe_from_objective(objective)
        else:
            sharpe = None

        return (
            DomainEvaluationMetric(
                metric_id="sharpe_ratio",
                value=sharpe,
                unit="ratio",
                comparison_convention="higher_is_better",
                provenance="computed_from_objective",
            ),
            DomainEvaluationMetric(
                metric_id="expected_return",
                value=metrics.expected_return,
                unit="annualized_decimal",
                comparison_convention="higher_is_better",
                provenance="computed_from_weights",
            ),
            DomainEvaluationMetric(
                metric_id="volatility",
                value=metrics.volatility,
                unit="annualized_decimal",
                comparison_convention="lower_is_better",
                provenance="computed_from_weights",
            ),
            DomainEvaluationMetric(
                metric_id="position_count",
                value=float(metrics.effective_positions) if metrics.effective_positions else None,
                unit="count",
                comparison_convention="neutral",
                provenance="computed_from_weights",
            ),
            DomainEvaluationMetric(
                metric_id="max_weight",
                value=metrics.max_weight,
                unit="decimal",
                comparison_convention="neutral",
                provenance="computed_from_weights",
            ),
            DomainEvaluationMetric(
                metric_id="objective_value",
                value=objective,
                unit="transformed_variance",
                comparison_convention="lower_is_better",
                provenance="recomputed_in_postcheck",
            ),
        )

    def _empty_metrics(self) -> tuple[DomainEvaluationMetric, ...]:
        """Return metrics with None values when solution is not reconstructible."""
        return (
            DomainEvaluationMetric(
                metric_id="sharpe_ratio",
                value=None,
                unit="ratio",
                comparison_convention="higher_is_better",
                provenance="not_available",
            ),
            DomainEvaluationMetric(
                metric_id="expected_return",
                value=None,
                unit="annualized_decimal",
                comparison_convention="higher_is_better",
                provenance="not_available",
            ),
            DomainEvaluationMetric(
                metric_id="volatility",
                value=None,
                unit="annualized_decimal",
                comparison_convention="lower_is_better",
                provenance="not_available",
            ),
            DomainEvaluationMetric(
                metric_id="position_count",
                value=None,
                unit="count",
                comparison_convention="neutral",
                provenance="not_available",
            ),
            DomainEvaluationMetric(
                metric_id="max_weight",
                value=None,
                unit="decimal",
                comparison_convention="neutral",
                provenance="not_available",
            ),
            DomainEvaluationMetric(
                metric_id="objective_value",
                value=None,
                unit="transformed_variance",
                comparison_convention="lower_is_better",
                provenance="not_available",
            ),
        )

    def identify_reducible_items(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
    ) -> list[str]:
        """Return ticker IDs available for reduction.

        Args:
            problem: Original or transformed problem.

        Returns:
            List of ticker IDs that can be reduced.
        """
        if isinstance(problem, TransformedSharpeProblem):
            return list(problem.retained_tickers)
        return list(problem.tickers)

    def describe_logical_variables(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
    ) -> LogicalVariableCounts:
        """Count logical variables in the problem.

        Args:
            problem: Original or transformed problem.

        Returns:
            Variable counts by type.
        """
        if isinstance(problem, TransformedSharpeProblem):
            original = problem.original_problem
            fixed_vars = {
                var for entry in problem.fixing_manifest.entries
                for var in entry.variable_values
            }
            mapping = problem.variable_mapping
        else:
            original = problem
            fixed_vars = set()
            mapping = SharpeVariableMapping.for_problem(problem)

        len(original.tickers)

        # Count free binary variables (delta, if cardinality constraint)
        binary_free = 0
        if original.max_positions is not None and mapping.delta_by_ticker:
            binary_free = sum(
                1 for t in original.tickers
                if mapping.delta_by_ticker[t] not in fixed_vars
            )

        # Count free continuous variables (x_scaled + x_scale)
        continuous_free = 1  # x_scale is always present
        continuous_free += sum(
            1 for t in original.tickers
            if mapping.x_scaled_by_ticker[t] not in fixed_vars
        )

        return LogicalVariableCounts(
            binary_free=binary_free,
            integer_free=0,
            continuous_free=continuous_free,
        )

    def build_conflict_graph(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
        state: object | None = None,
    ) -> ReductionGraph:
        """Build MWIS reduction graph.

        Args:
            problem: Original or transformed problem.
            state: Unused pipeline state.

        Returns:
            ReductionGraph for MWIS solving.
        """
        del state
        available = self.identify_reducible_items(problem)
        return build_sharpe_reduction_graph(
            problem, self._graph_policy, available_tickers=available
        )

    def declare_protected_items(
        self,
        problem: SharpePortfolioProblem,
    ) -> tuple[str, ...]:
        """Declare items that must be retained.

        Currently no items are protected by default.

        Args:
            problem: The original problem.

        Returns:
            Tuple of protected ticker IDs (empty).
        """
        del problem
        return ()

    def validate_candidate_domain(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult:
        """Validate that retained tickers can form a feasible solution.

        Checks:
        - No duplicate or unknown tickers
        - Retained tickers can satisfy unit budget
        - Sector constraints can be satisfied (if configured)
        - Cardinality constraint is satisfiable

        Args:
            problem: Original or transformed problem.
            retained_item_ids: Tickers to retain.

        Returns:
            Validation result with minimum required items if valid.
        """
        retained = tuple(retained_item_ids)

        # Check duplicates
        if len(set(retained)) != len(retained):
            return DomainValidationResult(
                False, None, failure_reasons=("duplicate_retained_ticker",)
            )

        # Check unknown tickers
        available = set(self.identify_reducible_items(problem))
        unknown = sorted(set(retained) - available)
        if unknown:
            return DomainValidationResult(
                False, None, failure_reasons=("unknown_ticker",)
            )

        # Get original problem
        if isinstance(problem, TransformedSharpeProblem):
            original = problem.original_problem
        else:
            original = problem

        tolerance = original.covariance_symmetry_tolerance
        n_retained = len(retained)

        # Compute minimum items for budget
        minimum_required = self._minimum_items_for_budget(original, retained)

        # Check cardinality constraint
        if original.max_positions is not None and n_retained < 1:
            return DomainValidationResult(
                False, minimum_required,
                failure_reasons=("empty_domain_with_cardinality",)
            )

        # Check budget capacity with retained upper bounds
        sorted_uppers = sorted(
            (original.upper_bounds[t] for t in retained), reverse=True
        )
        if original.max_positions is not None:
            effective_max = min(original.max_positions, n_retained)
        else:
            effective_max = n_retained

        capacity = sum(sorted_uppers[:effective_max])
        if capacity < 1 - tolerance:
            return DomainValidationResult(
                False, minimum_required,
                failure_reasons=(
                    f"insufficient_budget_capacity:{capacity:.6g}",
                )
            )

        # Check sector constraints
        if original.sector_constraints is not None:
            sector_issues = self._validate_sector_coverage(original, retained)
            if sector_issues:
                return DomainValidationResult(
                    False, minimum_required,
                    failure_reasons=tuple(sector_issues)
                )

        return DomainValidationResult(True, minimum_required)

    def _minimum_items_for_budget(
        self,
        problem: SharpePortfolioProblem,
        retained: tuple[str, ...],
    ) -> int:
        """Compute minimum items needed to satisfy unit budget."""
        tolerance = problem.covariance_symmetry_tolerance
        sorted_uppers = sorted(
            (problem.upper_bounds[t] for t in retained), reverse=True
        )

        cumulative = 0.0
        for i, ub in enumerate(sorted_uppers, start=1):
            cumulative += ub
            if cumulative >= 1 - tolerance:
                return i

        return len(retained)

    def _validate_sector_coverage(
        self,
        problem: SharpePortfolioProblem,
        retained: tuple[str, ...],
    ) -> list[str]:
        """Check if retained tickers can satisfy sector constraints.

        Validates:
        1. Each sector with min > 0 has retained tickers
        2. Each sector has enough capacity for its minimum
        3. Total capacity across all sectors (respecting maxima) >= 1
        """
        if problem.sector_constraints is None:
            return []

        issues: list[str] = []
        retained_set = set(retained)
        tol = problem.covariance_symmetry_tolerance

        # Track effective capacity per sector (respecting max constraints)
        sector_capacities: dict[str, float] = {}

        for sector in problem.sector_constraints.sectors:
            min_exposure = problem.sector_constraints.sector_min[sector]
            max_exposure = problem.sector_constraints.sector_max[sector]

            # Get retained tickers in this sector
            sector_tickers = [
                t for t in problem.tickers_in_sector(sector)
                if t in retained_set
            ]

            # Check if minimum can be satisfied
            if min_exposure > 0 and not sector_tickers:
                issues.append(
                    f"sector_{sector}_no_retained_tickers_for_min_{min_exposure:.4f}"
                )
                continue

            # Compute raw capacity from upper bounds
            raw_capacity = sum(problem.upper_bounds[t] for t in sector_tickers)

            # Check raw capacity covers minimum
            if raw_capacity < min_exposure - tol:
                issues.append(
                    f"sector_{sector}_capacity_{raw_capacity:.4f}_below_min_{min_exposure:.4f}"
                )

            # Effective capacity is limited by sector maximum
            sector_capacities[sector] = min(max_exposure, raw_capacity)

        # If there are already issues with individual sectors, return early
        if issues:
            return issues

        # Check that total sector-constrained capacity can cover unit budget
        # This catches the case where all retained tickers are in low-max sectors
        total_capacity = sum(sector_capacities.values())
        if total_capacity < 1.0 - tol:
            issues.append(
                f"total_sector_capacity_{total_capacity:.4f}_below_unit_budget"
            )

        return issues

    def build_fixing_manifest(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
        retained_item_ids: tuple[str, ...],
    ) -> FixingManifest:
        """Build fixing manifest for excluded tickers.

        Excluded tickers get x_scaled = 0 and delta = 0 (if present).

        Args:
            problem: Original or transformed problem.
            retained_item_ids: Tickers to retain.

        Returns:
            FixingManifest with entries for excluded tickers.

        Raises:
            ValueError: If candidate domain is invalid.
        """
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot build fixing manifest for invalid domain.")

        retained = tuple(retained_item_ids)
        retained_set = set(retained)
        available = self.identify_reducible_items(problem)

        # Get original problem
        if isinstance(problem, TransformedSharpeProblem):
            original = problem.original_problem
        else:
            original = problem

        mapping = SharpeVariableMapping.for_problem(original)

        # Build entries for excluded tickers
        excluded = tuple(t for t in available if t not in retained_set)
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
                reason="mwis_heuristic_exclusion",
            ))

        return FixingManifest(
            retained_item_ids=retained,
            excluded_item_ids=excluded,
            entries=tuple(entries),
            origin="heuristic_candidate_domain",
            provenance={
                "optimality_preservation_claim": "none",
                "graph_policy_id": self._graph_policy.policy_id,
                "graph_policy_version": self._graph_policy.policy_version,
            },
        )

    def restrict_problem(
        self,
        problem: SharpePortfolioProblem | TransformedSharpeProblem,
        retained_item_ids: tuple[str, ...],
        fixing_manifest: FixingManifest,
    ) -> TransformedSharpeProblem:
        """Build restricted problem with cumulative fixings.

        Args:
            problem: Original or transformed problem.
            retained_item_ids: Tickers to retain.
            fixing_manifest: Fixing manifest for this round.

        Returns:
            TransformedSharpeProblem ready for classical solver.

        Raises:
            ValueError: If candidate domain is invalid.
        """
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot restrict invalid candidate domain.")

        # Get original problem
        if isinstance(problem, TransformedSharpeProblem):
            original = problem.original_problem
            previous_manifest = problem.fixing_manifest

            # If no new exclusions, preserve the previous manifest unchanged
            # This makes applying an empty manifest to an already-restricted domain identity
            if not fixing_manifest.excluded_item_ids and not fixing_manifest.entries:
                fixing_manifest = previous_manifest
            else:
                # Merge manifests, preserving provenance from both sources
                merged_provenance: dict[str, object] = {}
                if previous_manifest.provenance:
                    merged_provenance["previous"] = dict(previous_manifest.provenance)
                if fixing_manifest.provenance:
                    merged_provenance["current"] = dict(fixing_manifest.provenance)
                merged_provenance["previous_origin"] = previous_manifest.origin
                merged_provenance["current_origin"] = fixing_manifest.origin

                # Merge source_candidate_ids preserving order and avoiding duplicates
                seen_candidate_ids: set[str] = set()
                merged_candidate_ids: list[str] = []
                for cid in previous_manifest.source_candidate_ids + fixing_manifest.source_candidate_ids:
                    if cid not in seen_candidate_ids:
                        seen_candidate_ids.add(cid)
                        merged_candidate_ids.append(cid)

                # Merge policy_version: use latest if equal, concatenate if different
                prev_policy = previous_manifest.policy_version
                curr_policy = fixing_manifest.policy_version
                if prev_policy is None:
                    merged_policy = curr_policy
                elif curr_policy is None or prev_policy == curr_policy:
                    merged_policy = prev_policy
                else:
                    merged_policy = f"{prev_policy}+{curr_policy}"

                fixing_manifest = FixingManifest(
                    retained_item_ids=tuple(retained_item_ids),
                    excluded_item_ids=(
                        previous_manifest.excluded_item_ids +
                        fixing_manifest.excluded_item_ids
                    ),
                    entries=previous_manifest.entries + fixing_manifest.entries,
                    origin=f"merged:{previous_manifest.origin}+{fixing_manifest.origin}",
                    round_index=fixing_manifest.round_index,
                    provenance=merged_provenance,
                    source_candidate_ids=tuple(merged_candidate_ids),
                    policy_version=merged_policy,
                )
        else:
            original = problem

        return TransformedSharpeProblem(
            original_problem=original,
            retained_tickers=retained_item_ids,
            fixing_manifest=fixing_manifest,
            variable_mapping=SharpeVariableMapping.for_problem(original),
        )

    def build_residual_model(
        self,
        reduced_problem: TransformedSharpeProblem,
        fixing_manifest: FixingManifest,
    ) -> object:
        """Build classical model from reduced problem.

        .. deprecated::
            The pipeline now uses ClassicalModelProvider protocol directly.
            This method is retained for backward compatibility.

        Args:
            reduced_problem: The restricted problem.
            fixing_manifest: The fixing manifest.

        Returns:
            ClassicalOptimizationModel for the solver.
        """
        import warnings
        warnings.warn(
            "build_residual_model is deprecated. Pipeline uses "
            "ClassicalModelProvider protocol directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        return reduced_problem.build_classical_model()

    def validate_final_solution(
        self,
        original_problem: SharpePortfolioProblem | TransformedSharpeProblem,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: ClassicalSolveOptions,
        solver_objective_value: float | None = None,
    ) -> FinalSolutionValidationResult:
        """Validate final solution through postcheck.

        Args:
            original_problem: The original Sharpe problem, or TransformedSharpeProblem.
            solution: Variable values from solver.
            fixing_manifest: Cumulative fixing manifest.
            tolerances: Tolerance settings for validation.
            solver_objective_value: Objective value reported by solver.

        Returns:
            FinalSolutionValidationResult with pass/fail and diagnostics.
        """
        if not isinstance(solution, Mapping):
            raise TypeError("Solution must be a variable-value mapping.")

        return validate_sharpe_solution(
            problem=original_problem,
            variable_values=solution,
            fixing_manifest=fixing_manifest,
            tolerances=tolerances,
            solver_objective_value=solver_objective_value,
        )
