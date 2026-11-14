"""Shared classical-backend execution and result normalization."""

from dataclasses import replace

from qreduce.domains import (
    DomainEvaluationMetric,
    FinalSolutionValidationResult,
    ReducibleProblemAdapter,
)
from qreduce.solving.residual import ClassicalSolveRequest, ClassicalSolveResult


def execute_classical_solver(
    solver: object,
    problem: object,
    request: ClassicalSolveRequest,
    *,
    staging_path: str | None,
    logical_path: str | None,
) -> ClassicalSolveResult:
    """Invoke an extension, validate its contract, and hide staging paths."""
    result = solver.solve(problem, request)  # type: ignore[attr-defined]
    if not isinstance(result, ClassicalSolveResult):
        raise TypeError("Classical backend must return ClassicalSolveResult.")
    if staging_path and result.model_export_path:
        result = replace(result, model_export_path=logical_path)
    return result


def evaluate_domain_metrics(
    problem: object,
    adapter: ReducibleProblemAdapter,
    classical_result: ClassicalSolveResult | None,
    postcheck_result: FinalSolutionValidationResult,
) -> tuple[DomainEvaluationMetric, ...]:
    """Evaluate and validate mandatory domain metrics after a post-check."""
    evaluate = getattr(adapter, "evaluate_domain_metrics", None)
    if not callable(evaluate):
        raise TypeError("Adapter must implement evaluate_domain_metrics.")
    metrics = evaluate(problem, classical_result, postcheck_result)
    if not isinstance(metrics, tuple | list) or any(
        not isinstance(metric, DomainEvaluationMetric) for metric in metrics
    ):
        raise TypeError("evaluate_domain_metrics must return a sequence of DomainEvaluationMetric.")
    if len({metric.metric_id for metric in metrics}) != len(metrics):
        raise ValueError("Domain metric IDs must be unique within a run.")
    return tuple(metrics)