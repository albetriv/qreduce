"""Lazy PySCIPOpt backend for generic residual MILP and MIQP models."""

from importlib import import_module as _import_module
from time import perf_counter
from typing import Any

from qreduce.classical.capabilities import ClassicalRuntimeCapabilities
from qreduce.classical.contracts import ClassicalSolveRequest, ClassicalSolveResult
from qreduce.classical.model import (
    ClassicalModelProvider,
    ClassicalOptimizationModel,
    ClassicalVariableType,
    LinearConstraintSense,
)
from qreduce.status import ClassicalSolverStatus, TerminalReason


class ScipClassicalBackend:
    """Solve generic residual models through an optional lazy PySCIPOpt binding."""

    solver_id = "scip"

    def capabilities(self) -> ClassicalRuntimeCapabilities:
        """Report optional binding availability without creating a SCIP model."""

        try:
            _import_module("pyscipopt")
        except (ImportError, ModuleNotFoundError):
            return ClassicalRuntimeCapabilities(
                solver_id=self.solver_id,
                runtime_available=False,
                supports_milp=True,
                supports_miqp=True,
                supports_random_seed=True,
                supports_threads=True,
                supports_mip_gap=True,
                supports_model_export=True,
                binding_importable=False,
                license_environment_available=True,
                diagnostic_message="The optional PySCIPOpt binding is not importable.",
            )
        return ClassicalRuntimeCapabilities(
            solver_id=self.solver_id,
            runtime_available=True,
            supports_milp=True,
            supports_miqp=True,
            supports_random_seed=True,
            supports_threads=True,
            supports_mip_gap=True,
            supports_model_export=True,
            binding_importable=True,
            license_environment_available=True,
        )

    def solve(self, reduced_problem: object, request: ClassicalSolveRequest) -> ClassicalSolveResult:
        """Solve one residual model or return an explicit, normalized failure result."""

        if request.requested_solver_id != self.solver_id:
            return _failure_result(
                request,
                ClassicalSolverStatus.FAILED,
                TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE,
                f"ScipClassicalBackend cannot execute requested solver '{request.requested_solver_id}'.",
            )
        if request.effective_time_limit_seconds is None:
            return _not_run_result(request)
        if not isinstance(reduced_problem, ClassicalModelProvider):
            return _failure_result(
                request,
                ClassicalSolverStatus.FAILED,
                TerminalReason.UNSUPPORTED_PROBLEM_STRUCTURE,
                "ScipClassicalBackend requires a ClassicalModelProvider residual problem.",
            )
        try:
            scip_module = _import_module("pyscipopt")
        except (ImportError, ModuleNotFoundError):
            return _failure_result(
                request,
                ClassicalSolverStatus.UNAVAILABLE,
                TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE,
                "The optional PySCIPOpt binding is not importable.",
            )
        started_at = perf_counter()
        try:
            generic_model = reduced_problem.build_classical_model()
            model, variables = _build_scip_model(scip_module, generic_model)
            effective_parameters = _configure_model(model, request)
            if request.model_export_enabled:
                model.writeProblem(request.model_export_path)
            model.optimize()
            return _result_from_model(model, variables, request, perf_counter() - started_at, effective_parameters)
        except Exception as error:  # noqa: BLE001 - third-party runtime failures are normalized.
            return _failure_result(
                request,
                ClassicalSolverStatus.FAILED,
                _terminal_reason_for_scip_exception(error),
                f"{type(error).__name__}: {error}",
                runtime_seconds=perf_counter() - started_at,
            )


def _build_scip_model(scip_module: Any, generic_model: ClassicalOptimizationModel) -> tuple[Any, dict[str, Any]]:
    model = scip_module.Model("qreduce_residual")
    type_by_variable = {
        ClassicalVariableType.BINARY: "B",
        ClassicalVariableType.CONTINUOUS: "C",
        ClassicalVariableType.INTEGER: "I",
    }
    variables = {
        variable.name: model.addVar(
            name=variable.name,
            vtype=type_by_variable[variable.variable_type],
            lb=variable.lower_bound if variable.lower_bound is not None else -model.infinity(),
            ub=variable.upper_bound if variable.upper_bound is not None else model.infinity(),
        )
        for variable in generic_model.variables
    }
    objective = sum(coefficient * variables[name] for name, coefficient in generic_model.linear_objective.items())
    objective += sum(
        term.coefficient
        * variables[term.left_variable]
        * variables[term.right_variable]
        for term in generic_model.quadratic_objective
    )
    model.setObjective(objective, sense="minimize")
    for constraint in generic_model.linear_constraints:
        expression = sum(coefficient * variables[name] for name, coefficient in constraint.coefficients.items())
        if constraint.sense is LinearConstraintSense.EQUAL:
            model.addCons(expression == constraint.right_hand_side, name=constraint.name)
        elif constraint.sense is LinearConstraintSense.LESS_EQUAL:
            model.addCons(expression <= constraint.right_hand_side, name=constraint.name)
        else:
            model.addCons(expression >= constraint.right_hand_side, name=constraint.name)
    return model, variables


def _configure_model(model: Any, request: ClassicalSolveRequest) -> dict[str, object]:
    effective_parameters: dict[str, object] = {"time_limit_seconds": request.effective_time_limit_seconds}
    model.setParam("limits/time", request.effective_time_limit_seconds)
    if request.mip_gap_tolerance is not None:
        model.setParam("limits/gap", request.mip_gap_tolerance)
        effective_parameters["mip_gap_tolerance"] = request.mip_gap_tolerance
    if request.threads is not None:
        model.setParam("parallel/maxnthreads", request.threads)
        effective_parameters["threads"] = request.threads
    if request.random_seed is not None:
        model.setParam("randomization/randomseedshift", request.random_seed)
        effective_parameters["random_seed"] = request.random_seed
    for parameter, value in request.solver_parameters.items():
        model.setParam(parameter, value)
        effective_parameters[parameter] = value
    return effective_parameters


def _result_from_model(model: Any, variables: dict[str, Any], request: ClassicalSolveRequest, runtime_seconds: float, effective_parameters: dict[str, object]) -> ClassicalSolveResult:
    status_text = str(model.getStatus()).lower()
    solution = model.getBestSol() if model.getNSols() > 0 else None
    has_solution = solution is not None
    is_optimal = status_text == "optimal"
    is_time_limited = status_text in {"timelimit", "time_limit"}
    if is_optimal:
        status = ClassicalSolverStatus.OPTIMAL
        terminal_reason = None
    elif "infeasible" in status_text:
        status = ClassicalSolverStatus.INFEASIBLE
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_INFEASIBLE
    elif is_time_limited and has_solution:
        status = ClassicalSolverStatus.TIME_LIMIT_WITH_FEASIBLE_INCUMBENT
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_TIME_LIMITED
    elif is_time_limited:
        status = ClassicalSolverStatus.TIME_LIMIT_WITHOUT_FEASIBLE_INCUMBENT
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_TIME_LIMITED
    elif has_solution:
        status = ClassicalSolverStatus.FEASIBLE
        terminal_reason = None
    else:
        status = ClassicalSolverStatus.FAILED
        terminal_reason = TerminalReason.CLASSICAL_SOLVER_FAILED
    return ClassicalSolveResult(
        classical_solver_status=status,
        terminal_reason=terminal_reason,
        solver_claimed_feasible=has_solution,
        objective_value=float(model.getObjVal()) if has_solution else None,
        best_bound=_optional_model_value(model, "getDualbound"),
        gap=_optional_model_value(model, "getGap"),
        is_optimal=is_optimal,
        is_time_limited=is_time_limited,
        runtime_seconds=runtime_seconds,
        variable_values=(
            {
                name: float(model.getSolVal(solution, variable))
                for name, variable in variables.items()
            }
            if solution is not None
            else {}
        ),
        variable_count=model.getNVars(),
        constraint_count=model.getNConss(),
        effective_solver_parameters=effective_parameters,
        model_export_path=request.model_export_path if request.model_export_enabled else None,
        remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
        diagnostic_message=None if status is not ClassicalSolverStatus.FAILED else f"SCIP status: {status_text}",
        requested_solver_id=request.requested_solver_id,
        effective_solver_id="scip",
    )


def _not_run_result(request: ClassicalSolveRequest) -> ClassicalSolveResult:
    return ClassicalSolveResult(
        ClassicalSolverStatus.NOT_RUN,
        TerminalReason.END_TO_END_TIME_BUDGET_EXHAUSTED,
        False,
        None,
        None,
        None,
        False,
        False,
        0.0,
        remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
        diagnostic_message="No positive end-to-end time budget remains for the classical backend.",
        requested_solver_id=request.requested_solver_id,
    )


def _failure_result(
    request: ClassicalSolveRequest,
    status: ClassicalSolverStatus,
    terminal_reason: TerminalReason,
    diagnostic_message: str,
    *,
    runtime_seconds: float = 0.0,
) -> ClassicalSolveResult:
    return ClassicalSolveResult(
        status,
        terminal_reason,
        False,
        None,
        None,
        None,
        False,
        False,
        runtime_seconds,
        remaining_time_budget_at_start_seconds=request.remaining_end_to_end_seconds,
        diagnostic_message=diagnostic_message,
        requested_solver_id=request.requested_solver_id,
    )


def _optional_model_value(model: Any, method_name: str) -> float | None:
    try:
        return float(getattr(model, method_name)())
    except Exception:  # noqa: BLE001 - metric availability depends on terminal status.
        return None


def _terminal_reason_for_scip_exception(error: Exception) -> TerminalReason:
    diagnostic_text = f"{type(error).__name__}: {error}".lower()
    if "license" in diagnostic_text or "licence" in diagnostic_text:
        return TerminalReason.CLASSICAL_BACKEND_UNAVAILABLE
    return TerminalReason.CLASSICAL_SOLVER_FAILED