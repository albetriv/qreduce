"""Adapter from synthetic mean-variance data to QReduce domain contracts."""

from qreduce.domains.contracts import (
    DomainValidationResult,
    FinalSolutionValidationResult,
    FixingEntry,
    FixingManifest,
)
from qreduce.domains.portfolio.models import (
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioResidualProblem,
    PortfolioVariableMapping,
)
from qreduce.domains.portfolio.postcheck import validate_portfolio_solution
from qreduce.models import ClassicalSolveOptions
from qreduce.mwis import ReductionGraph


class MeanVariancePortfolioAdapter:
    """Build reduction artifacts and validate solutions for a mean-variance MIQP."""

    def __init__(self, graph_policy: PortfolioGraphPolicy) -> None:
        self._graph_policy = graph_policy

    def identify_reducible_items(self, problem: PortfolioProblem) -> list[str]:
        return list(problem.asset_ids)

    def build_conflict_graph(self, problem: PortfolioProblem, state: object | None = None) -> ReductionGraph:
        del state
        edges: list[tuple[str, str]] = []
        edge_reasons: dict[tuple[str, str], str] = {}
        for left_index, left_asset_id in enumerate(problem.asset_ids):
            for right_asset_id in problem.asset_ids[left_index + 1 :]:
                absolute_correlation = abs(problem.correlation(left_asset_id, right_asset_id))
                if absolute_correlation >= self._graph_policy.correlation_absolute_threshold:
                    edge = (left_asset_id, right_asset_id) if left_asset_id < right_asset_id else (right_asset_id, left_asset_id)
                    edges.append(edge)
                    edge_reasons[edge] = (
                        f"abs_correlation={absolute_correlation:.12g} >= "
                        f"threshold={self._graph_policy.correlation_absolute_threshold:.12g}"
                    )
        ordered_edges = tuple(sorted(edges))
        return ReductionGraph(
            node_ids=problem.asset_ids,
            node_weights=problem.retention_scores,
            edges=ordered_edges,
            edge_reasons={edge: edge_reasons[edge] for edge in ordered_edges},
            graph_policy_id=self._graph_policy.policy_id,
            graph_policy_version=self._graph_policy.policy_version,
        )

    def validate_candidate_domain(
        self,
        problem: PortfolioProblem,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult:
        retained = tuple(retained_item_ids)
        if len(set(retained)) != len(retained):
            return DomainValidationResult(False, None, failure_reasons=("duplicate_retained_item_id",))
        unknown_items = sorted(set(retained) - set(problem.asset_ids))
        if unknown_items:
            return DomainValidationResult(False, None, failure_reasons=("unknown_retained_item_id",))
        retained_upper_bound = sum(problem.upper_bounds[asset_id] for asset_id in retained)
        minimum_required_items = _minimum_items_for_budget(problem)
        if retained_upper_bound < 1 - problem.covariance_symmetry_tolerance:
            return DomainValidationResult(
                False,
                minimum_required_items,
                failure_reasons=("retained_items_cannot_satisfy_unit_budget",),
            )
        return DomainValidationResult(True, minimum_required_items)

    def build_fixing_manifest(self, problem: PortfolioProblem, retained_item_ids: tuple[str, ...]) -> FixingManifest:
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot build a fixing manifest for an invalid candidate domain.")
        retained = tuple(retained_item_ids)
        retained_set = set(retained)
        mapping = PortfolioVariableMapping.for_problem(problem)
        excluded = tuple(asset_id for asset_id in problem.asset_ids if asset_id not in retained_set)
        entries = tuple(
            FixingEntry(
                item_id=asset_id,
                variable_values={
                    mapping.delta_variable_by_asset[asset_id]: 0.0,
                    mapping.x_variable_by_asset[asset_id]: 0.0,
                },
                reason="heuristic_candidate_domain_exclusion",
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
        problem: PortfolioProblem,
        retained_item_ids: tuple[str, ...],
        fixing_manifest: FixingManifest,
    ) -> PortfolioResidualProblem:
        validation = self.validate_candidate_domain(problem, retained_item_ids)
        if not validation.is_valid:
            raise ValueError("Cannot restrict an invalid candidate domain.")
        return PortfolioResidualProblem(
            original_problem=problem,
            retained_item_ids=retained_item_ids,
            fixing_manifest=fixing_manifest,
            variable_mapping=PortfolioVariableMapping.for_problem(problem),
        )

    def validate_final_solution(
        self,
        original_problem: PortfolioProblem,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: ClassicalSolveOptions,
    ) -> FinalSolutionValidationResult:
        if not isinstance(solution, dict):
            raise TypeError("Portfolio post-check expects a variable-value dictionary.")
        return validate_portfolio_solution(
            problem=original_problem,
            variable_values=solution,
            fixing_manifest=fixing_manifest,
            tolerances=tolerances,
        )


def _minimum_items_for_budget(problem: PortfolioProblem) -> int:
    cumulative_upper_bound = 0.0
    for item_count, upper_bound in enumerate(sorted(problem.upper_bounds.values(), reverse=True), start=1):
        cumulative_upper_bound += upper_bound
        if cumulative_upper_bound >= 1 - problem.covariance_symmetry_tolerance:
            return item_count
    return len(problem.asset_ids)