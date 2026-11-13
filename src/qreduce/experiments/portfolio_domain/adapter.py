"""Synthetic mean-variance portfolio adapter used only by repository experiments."""

from qreduce.domains.contracts import (
    DomainEvaluationMetric,
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
    LogicalVariableCounts,
)
from qreduce.experiments.portfolio_domain.models import (
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioResidualProblem,
    PortfolioVariableMapping,
)
from qreduce.experiments.portfolio_domain.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.mwis import ReductionGraph
from qreduce.solving.residual.contracts import ClassicalSolveResult


class MeanVariancePortfolioAdapter:
    """Build reduction artifacts and validate solutions for a mean-variance MIQP."""

    def __init__(self, graph_policy: PortfolioGraphPolicy) -> None:
        self._graph_policy = graph_policy

    def describe_input(self, problem: PortfolioProblem) -> object:
        """Expose the synthetic input for deterministic run identification."""
        return problem

    def evaluate_domain_metrics(
        self, problem: object, classical_result: ClassicalSolveResult,
        postcheck_result: FinalSolutionValidationResult,
    ) -> tuple[DomainEvaluationMetric, ...]:
        """The demonstration does not define external evaluation metrics."""
        return ()

    def identify_reducible_items(self, problem: PortfolioProblem | PortfolioResidualProblem) -> list[str]:
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
        retained = tuple(retained_item_ids)
        if len(set(retained)) != len(retained):
            return DomainValidationResult(False, None, failure_reasons=("duplicate_retained_item_id",))
        available = self.identify_reducible_items(problem)
        unknown_items = sorted(set(retained) - set(available))
        if unknown_items:
            return DomainValidationResult(False, None, failure_reasons=("unknown_retained_item_id",))
        if isinstance(problem, PortfolioResidualProblem):
            problem = problem.original_problem
        retained_upper_bound = sum(problem.upper_bounds[asset_id] for asset_id in retained)
        minimum_required_items = _minimum_items_for_budget(problem)
        if retained_upper_bound < 1 - problem.covariance_symmetry_tolerance:
            return DomainValidationResult(
                False,
                minimum_required_items,
                failure_reasons=("retained_items_cannot_satisfy_unit_budget",),
            )
        return DomainValidationResult(True, minimum_required_items)

    def build_fixing_manifest(self, problem: PortfolioProblem | PortfolioResidualProblem, retained_item_ids: tuple[str, ...]) -> FixingManifest:
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