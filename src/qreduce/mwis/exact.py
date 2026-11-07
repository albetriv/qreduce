"""Exhaustive, diagnostic-only exact MWIS/QUBO solver for small instances."""

from dataclasses import dataclass
from itertools import product

from qreduce.mwis.energy import qubo_energy
from qreduce.mwis.graph import ReductionGraph
from qreduce.mwis.qubo import CanonicalQubo
from qreduce.mwis.validation import MWISValidationError, validate_binary_selection


@dataclass(frozen=True, slots=True)
class ExactMWISResult:
    """Certified diagnostic outcome, intentionally distinct from RawMISSample."""

    node_order: tuple[str, ...]
    delta: tuple[int, ...]
    qubo_energy: float
    selection_weight: float
    is_independent_set: bool
    is_certified_qubo_optimum: bool
    is_certified_mwis_optimum: bool
    enumerated_assignment_count: int
    optimal_solution_count: int

    def to_dict(self) -> dict[str, object]:
        """Return a serializable exact-diagnostics result."""

        return {
            "node_order": list(self.node_order),
            "delta": list(self.delta),
            "qubo_energy": self.qubo_energy,
            "selection_weight": self.selection_weight,
            "is_independent_set": self.is_independent_set,
            "is_certified_qubo_optimum": self.is_certified_qubo_optimum,
            "is_certified_mwis_optimum": self.is_certified_mwis_optimum,
            "enumerated_assignment_count": self.enumerated_assignment_count,
            "optimal_solution_count": self.optimal_solution_count,
        }


def solve_exact_mwis(
    graph: ReductionGraph,
    qubo: CanonicalQubo,
    *,
    exact_solver_max_variables: int,
) -> ExactMWISResult:
    """Enumerate all binary assignments under an explicit diagnostic-only limit."""

    if qubo.node_order != graph.node_ids:
        raise MWISValidationError("node_order_mismatch", "qubo.node_order", "QUBO order must match graph node_ids.")
    if not isinstance(exact_solver_max_variables, int) or isinstance(exact_solver_max_variables, bool) or exact_solver_max_variables < 0:
        raise MWISValidationError(
            "invalid_exact_solver_max_variables",
            "exact_solver_max_variables",
            "Variable limit must be a non-negative integer.",
        )
    variable_count = len(graph.node_ids)
    if variable_count > exact_solver_max_variables:
        raise MWISValidationError(
            "exact_solver_variable_limit_exceeded",
            "exact_solver_max_variables",
            f"Instance has {variable_count} variables, exceeding the configured limit {exact_solver_max_variables}.",
        )

    assignments = tuple(product((0, 1), repeat=variable_count))
    energies = tuple(qubo_energy(qubo, assignment) for assignment in assignments)
    minimum_energy = min(energies)
    optimal_assignments = tuple(
        assignment for assignment, energy in zip(assignments, energies, strict=True) if energy == minimum_energy
    )
    chosen_delta = optimal_assignments[0]
    selected_validation = validate_binary_selection(graph, chosen_delta)
    maximum_independent_weight = max(
        (
            validate_binary_selection(graph, assignment).selection_weight
            for assignment in assignments
            if validate_binary_selection(graph, assignment).is_independent_set
        ),
        default=0.0,
    )
    is_certified_mwis_optimum = (
        qubo.proof_condition_satisfied
        and selected_validation.is_independent_set
        and selected_validation.selection_weight == maximum_independent_weight
    )
    return ExactMWISResult(
        node_order=graph.node_ids,
        delta=chosen_delta,
        qubo_energy=minimum_energy,
        selection_weight=selected_validation.selection_weight,
        is_independent_set=selected_validation.is_independent_set,
        is_certified_qubo_optimum=True,
        is_certified_mwis_optimum=is_certified_mwis_optimum,
        enumerated_assignment_count=len(assignments),
        optimal_solution_count=len(optimal_assignments),
    )