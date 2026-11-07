"""Uniform, serializable contracts for residual classical solver backends."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.status import ClassicalSolverStatus, TerminalReason


@dataclass(frozen=True, slots=True)
class ClassicalSolveRequest:
    """Resolved request to solve one opaque residual classical problem."""

    run_id: str
    round_index: int
    time_limit_seconds: float
    remaining_end_to_end_seconds: float
    mip_gap_tolerance: float | None
    random_seed: int | None
    threads: int | None
    model_export_enabled: bool
    model_export_path: str | None = None
    solver_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id cannot be blank.")
        if self.round_index < 0:
            raise ValueError("round_index must be non-negative.")
        _require_positive_finite(self.time_limit_seconds, "time_limit_seconds")
        _require_finite(self.remaining_end_to_end_seconds, "remaining_end_to_end_seconds")
        if self.mip_gap_tolerance is not None:
            _require_nonnegative_finite(self.mip_gap_tolerance, "mip_gap_tolerance")
        if self.threads is not None and self.threads < 1:
            raise ValueError("threads must be at least one when supplied.")
        if self.model_export_enabled and (self.model_export_path is None or not self.model_export_path.strip()):
            raise ValueError("model_export_path is required when model export is enabled.")
        object.__setattr__(self, "solver_parameters", MappingProxyType(dict(self.solver_parameters)))

    @property
    def effective_time_limit_seconds(self) -> float | None:
        """Return the positive time limit that the backend may actually consume."""

        if self.remaining_end_to_end_seconds <= 0:
            return None
        return min(self.time_limit_seconds, self.remaining_end_to_end_seconds)

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ClassicalSolveResult:
    """Normalized outcome returned by a classical residual solver."""

    classical_solver_status: ClassicalSolverStatus
    terminal_reason: TerminalReason | None
    solver_claimed_feasible: bool
    objective_value: float | None
    best_bound: float | None
    gap: float | None
    is_optimal: bool
    is_time_limited: bool
    runtime_seconds: float
    variable_values: Mapping[str, float] = field(default_factory=dict)
    variable_count: int | None = None
    constraint_count: int | None = None
    effective_solver_parameters: Mapping[str, object] = field(default_factory=dict)
    model_export_path: str | None = None
    remaining_time_budget_at_start_seconds: float | None = None
    diagnostic_message: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_finite(self.runtime_seconds, "runtime_seconds")
        if self.classical_solver_status is ClassicalSolverStatus.UNAVAILABLE and self.terminal_reason is None:
            raise ValueError("An unavailable solver result requires a terminal reason.")
        if self.classical_solver_status is ClassicalSolverStatus.FAILED and self.terminal_reason is None:
            raise ValueError("A failed solver result requires a terminal reason.")
        if self.classical_solver_status is ClassicalSolverStatus.INFEASIBLE and self.terminal_reason is None:
            raise ValueError("An infeasible solver result requires a terminal reason.")
        if self.is_optimal and self.classical_solver_status is not ClassicalSolverStatus.OPTIMAL:
            raise ValueError("Only an optimal result may claim optimality.")
        if self.is_time_limited and self.classical_solver_status not in {
            ClassicalSolverStatus.TIME_LIMIT_WITH_FEASIBLE_INCUMBENT,
            ClassicalSolverStatus.TIME_LIMIT_WITHOUT_FEASIBLE_INCUMBENT,
        }:
            raise ValueError("Only time-limited statuses may claim a time limit.")
        values = dict(self.variable_values)
        if any(not name.strip() or not math.isfinite(value) for name, value in values.items()):
            raise ValueError("variable_values must have non-blank names and finite values.")
        object.__setattr__(self, "variable_values", MappingProxyType(values))
        object.__setattr__(self, "effective_solver_parameters", MappingProxyType(dict(self.effective_solver_parameters)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


class ClassicalBackend(Protocol):
    """Uniform solver boundary; residual problems remain owned by adapters."""

    def solve(self, reduced_problem: object, request: ClassicalSolveRequest) -> ClassicalSolveResult: ...


def _require_finite(value: float, field_name: str) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite.")


def _require_positive_finite(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")


def _require_nonnegative_finite(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative.")