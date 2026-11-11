"""Lazy IBM ILOG CPLEX backend for generic residual MILP and MIQP models."""

from importlib import import_module as _import_module
from time import perf_counter
from typing import Any

from qreduce.classical.capabilities import ClassicalRuntimeCapabilities
from qreduce.classical.contracts import ClassicalSolveRequest, ClassicalSolveResult
from qreduce.classical.cplex_capability import cplex_classical_capabilities
from qreduce.classical.model import (
    ClassicalModelProvider,
    ClassicalOptimizationModel,
    ClassicalVariableType,
    LinearConstraintSense,
)
from qreduce.status import ClassicalSolverStatus, TerminalReason


class CplexClassicalBackend:
    """Solve residual problems compiled by a domain adapter into a generic model."""

    solver_id = "cplex"

    def capabilities(self) -> ClassicalRuntimeCapabilities:
        """Report binding availability without creating a CPLEX model."""

        return cplex_classical_capabilities()

    def solve(self, reduced_problem: object, request: ClassicalSolveRequest) -> ClassicalSolveResult:
        """Solve one residual problem or return a normalized, explicit failure result."""

        if request.requested_solver_id != self.solver_id:
            return _failure_result(
                request,
                ClassicalSolverStatus.FAILED,
                TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE,
                f"CplexClassicalBackend cannot execute requested solver '{request.requested_solver_id}'.",
            )
        if request.effective_time_limit_seconds is None:
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.NOT_RUN,
                terminal_reason=TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.0,
                remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
                diagnostic_message="No positive end-to-end time budget remains for the classical backend.",
                requested_solver_id=request.requested_solver_id,
            )
        if not isinstance(reduced_problem, ClassicalModelProvider):
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.FAILED,
                terminal_reason=TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.0,
                remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
                diagnostic_message="CplexClassicalBackend requires a ClassicalModelProvider residual problem.",
                requested_solver_id=request.requested_solver_id,
            )
        try:
            cplex_module = _import_module("cplex")
        except (ImportError, ModuleNotFoundError):
            return ClassicalSolveResult(
                classical_solver_status=ClassicalSolverStatus.UNAVAILABLE,
                terminal_reason=TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=0.0,
                remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
                diagnostic_message="The optional CPLEX Python binding is not importable.",
                requested_solver_id=request.requested_solver_id,
            )
        started_at = perf_counter()
        try:
            generic_model = reduced_problem.build_classical_model()
            model = _build_cplex_model(cplex_module, generic_model)
            variable_names = generic_model.variable_names
            effective_parameters = _configure_model(model, request)
            if request.model_export_enabled:
                model.write(request.model_export_path)
            model.solve()
            return _result_from_model(
                model=model,
                variable_names=variable_names,
                request=request,
                runtime_seconds=perf_counter() - started_at,
                effective_parameters=effective_parameters,
            )
        except Exception as error:  # noqa: BLE001 - Binding-specific errors must become serializable results.
            terminal_reason = _terminal_reason_for_cplex_exception(error)
            return ClassicalSolveResult(
                classical_solver_status=(
                    ClassicalSolverStatus.UNAVAILABLE
                    if terminal_reason is TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
                    else ClassicalSolverStatus.FAILED
                ),
                terminal_reason=terminal_reason,
                solver_claimed_feasible=False,
                objective_value=None,
                best_bound=None,
                gap=None,
                is_optimal=False,
                is_time_limited=False,
                runtime_seconds=perf_counter() - started_at,
                remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
                diagnostic_message=f"CPLEX solve failed: {type(error).__name__}: {error}",
                requested_solver_id=request.requested_solver_id,
            )


def _configure_model(model: Any, request: ClassicalSolveRequest) -> dict[str, object]:
    effective_parameters: dict[str, object] = {"time_limit_seconds": request.effective_time_limit_seconds}
    model.parameters.timelimit.set(request.effective_time_limit_seconds)
    if request.mip_gap_tolerance is not None:
        model.parameters.mip.tolerances.mipgap.set(request.mip_gap_tolerance)
        effective_parameters["mip_gap_tolerance"] = request.mip_gap_tolerance
    if request.random_seed is not None:
        model.parameters.randomseed.set(request.random_seed)
        effective_parameters["random_seed"] = request.random_seed
    if request.threads is not None:
        model.parameters.threads.set(request.threads)
        effective_parameters["threads"] = request.threads
    return effective_parameters


def _result_from_model(
    *,
    model: Any,
    variable_names: tuple[str, ...],
    request: ClassicalSolveRequest,
    runtime_seconds: float,
    effective_parameters: dict[str, object],
) -> ClassicalSolveResult:
    solution = model.solution
    status_text = str(solution.get_status_string()).lower()
    has_solution = bool(solution.is_primal_feasible())
    is_optimal = "optimal" in status_text and has_solution
    is_time_limited = "time limit" in status_text or "time_limit" in status_text
    if is_optimal:
        normalized_status = ClassicalSolverStatus.OPTIMAL
        terminal_reason = None
    elif "infeasible" in status_text:
        normalized_status = ClassicalSolverStatus.INFEASIBLE
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_INFEASIBLE
    elif is_time_limited and has_solution:
        normalized_status = ClassicalSolverStatus.TIME_LIMIT_WITH_FEASIBLE_INCUMBENT
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_TIME_LIMITED
    elif is_time_limited:
        normalized_status = ClassicalSolverStatus.TIME_LIMIT_WITHOUT_FEASIBLE_INCUMBENT
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_TIME_LIMITED
    elif has_solution:
        normalized_status = ClassicalSolverStatus.FEASIBLE
        terminal_reason = None
    else:
        normalized_status = ClassicalSolverStatus.FAILED
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_FAILED
    objective_value = solution.get_objective_value() if has_solution else None
    variable_values = dict(zip(variable_names, solution.get_values(variable_names), strict=True)) if has_solution else {}
    best_bound = _optional_solution_value(solution, "get_best_objective")
    gap = _optional_solution_value(solution.MIP, "get_mip_relative_gap") if hasattr(solution, "MIP") else None
    return ClassicalSolveResult(
        classical_solver_status=normalized_status,
        terminal_reason=terminal_reason,
        solver_claimed_feasible=has_solution,
        objective_value=objective_value,
        best_bound=best_bound,
        gap=gap,
        is_optimal=is_optimal,
        is_time_limited=is_time_limited,
        runtime_seconds=runtime_seconds,
        variable_values=variable_values,
        variable_count=model.variables.get_num(),
        constraint_count=model.linear_constraints.get_num(),
        effective_solver_parameters=effective_parameters,
        model_export_path=request.model_export_path if request.model_export_enabled else None,
        remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
        diagnostic_message=None if normalized_status is not ClassicalSolverStatus.FAILED else f"CPLEX status: {status_text}",
        requested_solver_id=request.requested_solver_id,
        effective_solver_id="cplex",
    )


def _failure_result(
    request: ClassicalSolveRequest,
    status: ClassicalSolverStatus,
    terminal_reason: TerminalReason,
    diagnostic_message: str,
) -> ClassicalSolveResult:
    return ClassicalSolveResult(
        classical_solver_status=status,
        terminal_reason=terminal_reason,
        solver_claimed_feasible=False,
        objective_value=None,
        best_bound=None,
        gap=None,
        is_optimal=False,
        is_time_limited=False,
        runtime_seconds=0.0,
        remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
        diagnostic_message=diagnostic_message,
        requested_solver_id=request.requested_solver_id,
    )


def _build_cplex_model(cplex_module: Any, generic_model: ClassicalOptimizationModel) -> Any:
    """Translate the solver-independent polynomial model into the CPLEX API."""

    model = cplex_module.Cplex()
    model.objective.set_sense(model.objective.sense.minimize)
    type_by_variable = {
        ClassicalVariableType.BINARY: model.variables.type.binary,
        ClassicalVariableType.CONTINUOUS: model.variables.type.continuous,
        ClassicalVariableType.INTEGER: model.variables.type.integer,
    }
    model.variables.add(
        names=list(generic_model.variable_names),
        types=[type_by_variable[variable.variable_type] for variable in generic_model.variables],
        lb=[variable.lower_bound if variable.lower_bound is not None else -cplex_module.infinity for variable in generic_model.variables],
        ub=[variable.upper_bound if variable.upper_bound is not None else cplex_module.infinity for variable in generic_model.variables],
    )
    model.objective.set_linear(list(generic_model.linear_objective.items()))
    model.objective.set_quadratic_coefficients(
        [
            (
                term.left_variable,
                term.right_variable,
                2.0 * term.coefficient
                if term.left_variable == term.right_variable
                else term.coefficient,
            )
            for term in generic_model.quadratic_objective
        ]
    )
    sense_by_constraint = {
        LinearConstraintSense.EQUAL: "E",
        LinearConstraintSense.LESS_EQUAL: "L",
        LinearConstraintSense.GREATER_EQUAL: "G",
    }
    model.linear_constraints.add(
        lin_expr=[
            cplex_module.SparsePair(ind=list(constraint.coefficients), val=list(constraint.coefficients.values()))
            for constraint in generic_model.linear_constraints
        ],
        senses=[sense_by_constraint[constraint.sense] for constraint in generic_model.linear_constraints],
        rhs=[constraint.right_hand_side for constraint in generic_model.linear_constraints],
        names=[constraint.name for constraint in generic_model.linear_constraints],
    )
    return model


def _optional_solution_value(target: Any, method_name: str) -> float | None:
    try:
        return float(getattr(target, method_name)())
    except Exception:  # noqa: BLE001 - Optional CPLEX solution metrics are unavailable for some statuses.
        return None


def _terminal_reason_for_cplex_exception(error: Exception) -> TerminalReason:
    """Classify binding/license startup failures without silently changing backend."""

    diagnostic_text = f"{type(error).__name__}: {error}".lower()
    if "license" in diagnostic_text or "licence" in diagnostic_text:
        return TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    return TerminalReason.CLASSICAL_SOLVER_FAILED