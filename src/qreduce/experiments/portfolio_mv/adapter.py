"""Synthetic mean-variance portfolio adapter used only by repository experiments."""

from qreduce.domains.contracts import (
    DomainEvaluationMetric,
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    LogicalVariableCounts,
)
from qreduce.experiments.portfolio_mv.models import (
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioResidualProblem,
    PortfolioVariableMapping,
)
from qreduce.experiments.portfolio_mv.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.mwis import ReductionGraph
from qreduce.solving.residual.contracts import ClassicalSolveResult


class MeanVariancePortfolioAdapter:
    """Build reduction artifacts and validate solutions for a mean-variance MIQP."""

    def __init__(self, graph_policy: PortfolioGraphPolicy) -> None:
        """Initialize with the graph policy defining edge criteria."""
        self._graph_policy = graph_policy

    def describe_input(self, problem: PortfolioProblem) -> object:
        """Expose the synthetic input for deterministic run identification."""
        return problem

    def evaluate_domain_metrics(
        self, problem: object, classical_result: ClassicalSolveResult,
        postcheck_result: FinalSolutionValidationResult,
    ) -> tuple[DomainEvaluationMetric, ...]:
        """Return an empty tuple; the demonstration does not define evaluation metrics."""
        return ()

    def identify_reducible_items(self, problem: PortfolioProblem | PortfolioResidualProblem) -> list[str]:
        """Return asset IDs available for reduction in the current problem."""
        if isinstance(problem, PortfolioResidualProblem):
            return list(problem.retained_item_ids)
        return list(problem.asset_ids)

    def describe_logical_variables(
        self, problem: PortfolioProblem | PortfolioResidualProblem
    ) -> LogicalVariableCounts:
        """Count explicit model decisions, excluding manifest-fixed variables."""
        if isinstance(problem, PortfolioResidualProblem):
            original = problem.original_problem
            fixed = {
                name for entry in problem.fixing_manifest.entries
                for name in entry.variable_values
            }
            mapping = problem.variable_mapping
        elif isinstance(problem, PortfolioProblem):
            original = problem
            fixed = set()
            mapping = PortfolioVariableMapping.for_problem(problem)
        else:
            raise TypeError("Unsupported portfolio problem for logical variable counts.")
        return LogicalVariableCounts(
            binary_free=sum(mapping.delta_variable_by_asset[asset] not in fixed for asset in original.asset_ids),
            integer_free=0,
            continuous_free=sum(mapping.x_variable_by_asset[asset] not in fixed for asset in original.asset_ids),
        )

    def build_conflict_graph(self, problem: PortfolioProblem | PortfolioResidualProblem, state: object | None = None) -> ReductionGraph:
        """Build edges based on correlation threshold and optional near-duplicate criteria."""
        del state
        item_ids = tuple(self.identify_reducible_items(problem))
        if isinstance(problem, PortfolioResidualProblem):
            problem = problem.original_problem
        edges: list[tuple[str, str]] = []
        edge_reasons: dict[tuple[str, str], str] = {}
        policy = self._graph_policy
        threshold = policy.correlation_absolute_threshold

        for left_index, left_asset_id in enumerate(item_ids):
            for right_asset_id in item_ids[left_index + 1:]:
                absolute_correlation = abs(problem.correlation(left_asset_id, right_asset_id))

                # Both modes require correlation threshold
                if absolute_correlation < threshold:
                    continue

                if policy.edge_mode == "correlation_only":
                    # Only correlation threshold applies
                    edge = (left_asset_id, right_asset_id) if left_asset_id < right_asset_id else (right_asset_id, left_asset_id)
                    edges.append(edge)
                    edge_reasons[edge] = (
                        f"edge_mode=correlation_only; "
                        f"abs_correlation={absolute_correlation:.6g} >= threshold={threshold:.6g}"
                    )

                elif policy.edge_mode == "near_duplicate":
                    # Additional checks for near-duplicate semantics
                    mu_left = problem.expected_returns[left_asset_id]
                    mu_right = problem.expected_returns[right_asset_id]
                    var_left = problem.covariance[problem.asset_index(left_asset_id)][problem.asset_index(left_asset_id)]
                    var_right = problem.covariance[problem.asset_index(right_asset_id)][problem.asset_index(right_asset_id)]

                    epsilon = 1e-12

                    # Relative return difference
                    max_abs_mu = max(abs(mu_left), abs(mu_right), epsilon)
                    relative_return_diff = abs(mu_left - mu_right) / max_abs_mu

                    # Relative variance difference
                    max_var = max(var_left, var_right, epsilon)
                    relative_variance_diff = abs(var_left - var_right) / max_var

                    max_return_diff = policy.near_duplicate_max_relative_return_difference
                    max_variance_diff = policy.near_duplicate_max_relative_variance_difference

                    assert max_return_diff is not None  # Validated in policy __post_init__
                    assert max_variance_diff is not None

                    # Check near-duplicate criteria
                    return_ok = relative_return_diff <= max_return_diff
                    variance_ok = relative_variance_diff <= max_variance_diff

                    if return_ok and variance_ok:
                        edge = (left_asset_id, right_asset_id) if left_asset_id < right_asset_id else (right_asset_id, left_asset_id)
                        edges.append(edge)
                        edge_reasons[edge] = (
                            f"edge_mode=near_duplicate; "
                            f"abs_correlation={absolute_correlation:.6g} >= threshold={threshold:.6g}; "
                            f"relative_return_difference={relative_return_diff:.6g} <= max={max_return_diff:.6g}; "
                            f"relative_variance_difference={relative_variance_diff:.6g} <= max={max_variance_diff:.6g}"
                        )

        ordered_edges = tuple(sorted(edges))
        return ReductionGraph(
            node_ids=item_ids,
            node_weights={item: problem.retention_scores[item] for item in item_ids},
            edges=ordered_edges,
            edge_reasons={edge: edge_reasons[edge] for edge in ordered_edges},
            graph_policy_id=self._graph_policy.policy_id,
            graph_policy_version=self._graph_policy.policy_version,
        )

    def declare_protected_items(self, problem: PortfolioProblem) -> tuple[str, ...]:
        """Return no additional protections for the baseline portfolio experiment."""
        del problem
        return ()

    def validate_candidate_domain(
        self,
        problem: PortfolioProblem | PortfolioResidualProblem,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult:
        """Check that retained assets can satisfy budget and cardinality constraints.

        Validates:
        - No duplicate or unknown item IDs
        - Retained items' upper bounds can satisfy the unit budget (considering max cardinality)
        - Retained item count satisfies minimum cardinality constraint
        - Retained items' lower bounds don't make minimum cardinality infeasible

        The key insight is:
        - max_selected_assets limits capacity: use top-k upper bounds
        - min_selected_assets requires minimum investment: use bottom-k lower bounds
        """
        retained = tuple(retained_item_ids)
        if len(set(retained)) != len(retained):
            return DomainValidationResult(False, None, failure_reasons=("duplicate_retained_item_id",))
        available = self.identify_reducible_items(problem)
        unknown_items = sorted(set(retained) - set(available))
        if unknown_items:
            return DomainValidationResult(False, None, failure_reasons=("unknown_retained_item_id",))
        if isinstance(problem, PortfolioResidualProblem):
            original_problem = problem.original_problem
        else:
            original_problem = problem

        tolerance = original_problem.covariance_symmetry_tolerance
        n_retained = len(retained)

        # Compute minimum items needed based on problem constraints
        minimum_required_items = _minimum_items_for_budget_with_cardinality(
            original_problem, retained
        )

        # Check minimum cardinality constraint: domain must have enough items
        if original_problem.min_selected_assets is not None and n_retained < original_problem.min_selected_assets:
            return DomainValidationResult(
                False,
                minimum_required_items,
                failure_reasons=(
                    f"retained_items_below_min_cardinality:retained={n_retained},required>={original_problem.min_selected_assets}",
                ),
            )

        # Check capacity: can we reach budget=1 with the available upper bounds?
        # If max_selected_assets is set, we can only use that many assets
        sorted_uppers = sorted(
            (original_problem.upper_bounds[a] for a in retained), reverse=True
        )
        if original_problem.max_selected_assets is not None:
            effective_max = min(original_problem.max_selected_assets, n_retained)
        else:
            effective_max = n_retained
        achievable_capacity = sum(sorted_uppers[:effective_max])
        if achievable_capacity < 1 - tolerance:
            return DomainValidationResult(
                False,
                minimum_required_items,
                failure_reasons=(
                    f"retained_items_cannot_satisfy_unit_budget:capacity={achievable_capacity:.6g},max_selectable={effective_max}",
                ),
            )

        # Check if minimum cardinality is feasible with lower bounds
        # We need to select at least min_selected_assets; the sum of their lower bounds must be <= 1
        if original_problem.min_selected_assets is not None and original_problem.min_selected_assets > 0:
            sorted_lowers = sorted(original_problem.lower_bounds[a] for a in retained)
            min_k = original_problem.min_selected_assets
            # Sum of the min_k smallest lower bounds (the cheapest selection)
            min_selection_cost = sum(sorted_lowers[:min_k])
            if min_selection_cost > 1 + tolerance:
                return DomainValidationResult(
                    False,
                    minimum_required_items,
                    failure_reasons=(
                        f"min_cardinality_infeasible:min_selection_cost={min_selection_cost:.6g},required_assets={min_k}",
                    ),
                )

        return DomainValidationResult(True, minimum_required_items)

    def build_fixing_manifest(self, problem: PortfolioProblem | PortfolioResidualProblem, retained_item_ids: tuple[str, ...]) -> FixingManifest:
        """Fix excluded assets' allocation and selection variables to zero."""
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot build a fixing manifest for an invalid candidate domain.")
        retained = tuple(retained_item_ids)
        retained_set = set(retained)
        available = self.identify_reducible_items(problem)
        original = problem.original_problem if isinstance(problem, PortfolioResidualProblem) else problem
        mapping = PortfolioVariableMapping.for_problem(original)
        excluded = tuple(asset_id for asset_id in available if asset_id not in retained_set)
        entries = tuple(
            FixingEntry(
                item_id=asset_id,
                variable_values={
                    mapping.delta_variable_by_asset[asset_id]: 0.0,
                    mapping.x_variable_by_asset[asset_id]: 0.0,
                },
                reason="mis_heuristic_exclusion",
            )
            for asset_id in excluded
        )
        return FixingManifest(
            retained_item_ids=retained,
            excluded_item_ids=excluded,
            entries=entries,
            origin="heuristic_candidate_domain",
            provenance={
                "optimality_preservation_claim": "none",
                "graph_policy_id": self._graph_policy.policy_id,
                "graph_policy_version": self._graph_policy.policy_version,
            },
        )

    def restrict_problem(
        self,
        problem: PortfolioProblem | PortfolioResidualProblem,
        retained_item_ids: tuple[str, ...],
        fixing_manifest: FixingManifest,
    ) -> PortfolioResidualProblem:
        """Build a residual problem with cumulative fixings from all rounds."""
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot restrict an invalid candidate domain.")
        original = problem.original_problem if isinstance(problem, PortfolioResidualProblem) else problem
        if isinstance(problem, PortfolioResidualProblem):
            previous = problem.fixing_manifest
            fixing_manifest = FixingManifest(
                retained_item_ids=tuple(retained_item_ids),
                excluded_item_ids=previous.excluded_item_ids + fixing_manifest.excluded_item_ids,
                entries=previous.entries + fixing_manifest.entries,
                origin="cumulative_round_fixings",
                round_index=fixing_manifest.round_index,
                provenance={"round_manifests_required_for_provenance": True},
            )
        return PortfolioResidualProblem(
            original_problem=original,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
            variable_mapping=PortfolioVariableMapping.for_problem(original),
        )

    def build_residual_model(
        self,
        reduced_problem: PortfolioResidualProblem,
        fixing_manifest: FixingManifest,
    ) -> object:
        """Build the classical optimization model from the reduced portfolio problem.

        .. deprecated:: 0.6.0
            This method is no longer called by the pipeline. The pipeline now
            passes the result of ``restrict_problem()`` directly to the classical
            solver, which calls ``build_classical_model()`` internally via the
            ``ClassicalModelProvider`` protocol.

            This method is retained for backward compatibility with code that
            may call it directly, but will be removed in a future version.
        """
        import warnings

        warnings.warn(
            "build_residual_model is deprecated. The pipeline now passes "
            "the restricted problem (ClassicalModelProvider) directly to the solver.",
            DeprecationWarning,
            stacklevel=2,
        )
        return reduced_problem.build_classical_model()

    def validate_final_solution(
        self,
        original_problem: PortfolioProblem,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: ClassicalSolveOptions,
        solver_objective_value: float | None = None,
    ) -> FinalSolutionValidationResult:
        """Verify budget, bounds, fixings, and objective via postcheck module."""
        from collections.abc import Mapping
        if not isinstance(solution, Mapping):
            raise TypeError("Portfolio post-check expects a variable-value mapping.")
        return validate_portfolio_solution(
            problem=original_problem,
            variable_values=solution,
            fixing_manifest=fixing_manifest,
            tolerances=tolerances,
            solver_objective_value=solver_objective_value,
        )


def _minimum_items_for_budget(problem: PortfolioProblem) -> int:
    cumulative_upper_bound = 0.0
    for item_count, upper_bound in enumerate(sorted(problem.upper_bounds.values(), reverse=True), start=1):
        cumulative_upper_bound += upper_bound
        if cumulative_upper_bound >= 1 - problem.covariance_symmetry_tolerance:
            return item_count
    return len(problem.asset_ids)


def _minimum_items_for_budget_with_cardinality(
    problem: PortfolioProblem,
    retained_ids: tuple[str, ...],
) -> int:
    """Compute minimum items needed considering cardinality constraints.

    Returns the maximum of:
    - Items needed to reach budget (based on upper bounds)
    - min_selected_assets constraint (if set)
    """
    tolerance = problem.covariance_symmetry_tolerance

    # Compute minimum based on upper bounds of retained assets
    sorted_uppers = sorted(
        (problem.upper_bounds[a] for a in retained_ids), reverse=True
    )
    cumulative = 0.0
    min_for_budget = len(retained_ids)
    for i, ub in enumerate(sorted_uppers, start=1):
        cumulative += ub
        if cumulative >= 1 - tolerance:
            min_for_budget = i
            break

    # Consider min_selected_assets constraint
    if problem.min_selected_assets is not None:
        return max(min_for_budget, problem.min_selected_assets)
    return min_for_budget