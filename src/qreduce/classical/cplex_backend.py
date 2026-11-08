"""Lazy IBM ILOG CPLEX backend for demonstrative portfolio residual MIQPs."""

from importlib import import_module as _import_module
from time import perf_counter
from typing import Any

from qreduce.classical.capabilities import ClassicalRuntimeCapabilities
from qreduce.classical.contracts import ClassicalSolveRequest, ClassicalSolveResult
from qreduce.classical.cplex_capability import cplex_classical_capabilities
from qreduce.domains.portfolio.models import PortfolioResidualProblem
from qreduce.solvers import BuiltinClassicalSolverId
from qreduce.status import ClassicalSolverStatus, TerminalReason


class CplexClassicalBackend:
    """Solve supported residual portfolio MIQPs without importing CPLEX at module load."""

    solver_id = BuiltinClassicalSolverId.CPLEX.value

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
        if not isinstance(reduced_problem, PortfolioResidualProblem):
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
                diagnostic_message="CplexClassicalBackend only supports PortfolioResidualProblem.",
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
            model, variable_names = _build_portfolio_model(cplex_module, reduced_problem)
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


def _build_portfolio_model(cplex_module: Any, residual_problem: PortfolioResidualProblem) -> tuple[Any, tuple[str, ...]]:
    problem = residual_problem.original_problem
    mapping = residual_problem.variable_mapping
    model = cplex_module.Cplex()
    model.objective.set_sense(model.objective.sense.minimize)
    asset_ids = problem.asset_ids
    delta_names = [mapping.delta_variable_by_asset[asset_id] for asset_id in asset_ids]
    x_names = [mapping.x_variable_by_asset[asset_id] for asset_id in asset_ids]
    model.variables.add(names=delta_names, types=[model.variables.type.binary] * len(asset_ids))
    model.variables.add(names=x_names, lb=[0.0] * len(asset_ids))
    model.objective.set_linear([(x_names[index], -problem.expected_returns[asset_id]) for index, asset_id in enumerate(asset_ids)])
    quadratic_coefficients = [
        (x_names[left_index], x_names[right_index], 2.0 * problem.risk_aversion * problem.covariance[left_index][right_index])
        for left_index in range(len(asset_ids))
        for right_index in range(left_index, len(asset_ids))
    ]
    model.objective.set_quadratic_coefficients(quadratic_coefficients)
    model.linear_constraints.add(
        lin_expr=[cplex_module.SparsePair(ind=x_names, val=[1.0] * len(asset_ids))],
        senses=["E"],
        rhs=[1.0],
        names=["budget"],
    )
    for asset_id in asset_ids:
        delta_name = mapping.delta_variable_by_asset[asset_id]
        x_name = mapping.x_variable_by_asset[asset_id]
        model.linear_constraints.add(
            lin_expr=[cplex_module.SparsePair(ind=[x_name, delta_name], val=[1.0, -problem.lower_bounds[asset_id]])],
            senses=["G"],
            rhs=[0.0],
            names=[f"lower_link__{asset_id}"],
        )
        model.linear_constraints.add(
            lin_expr=[cplex_module.SparsePair(ind=[x_name, delta_name], val=[1.0, -problem.upper_bounds[asset_id]])],
            senses=["L"],
            rhs=[0.0],
            names=[f"upper_link__{asset_id}"],
        )
    for entry in residual_problem.fixing_manifest.entries:
        for variable_name, value in entry.variable_values.items():
            model.linear_constraints.add(
                lin_expr=[cplex_module.SparsePair(ind=[variable_name], val=[1.0])],
                senses=["E"],
                rhs=[value],
                names=[f"fix__{entry.item_id}__{variable_name}"],
            )
    return model, tuple(delta_names + x_names)


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
        effective_solver_id=BuiltinClassicalSolverId.CPLEX.value,
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