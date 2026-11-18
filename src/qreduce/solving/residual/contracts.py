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
    """Resolved request to solve one opaque residual classical problem.

    Attributes:
        time_limit_seconds: Per-solve timeout. A value of 0 means no per-solve
            limit; the solver runs until completion or end-to-end budget exhaustion.
        remaining_end_to_end_seconds: Budget left at request creation time.
            May be <= 0 if the budget is exhausted. Ignored if budget is unlimited.
        configured_end_to_end_budget_seconds: Originally configured budget.
            A value of 0 means no global budget was configured (unlimited).
            This field is required to correctly distinguish "unlimited" from
            "exhausted" budget states.
    """

    run_id: str
    round_index: int
    time_limit_seconds: float
    remaining_end_to_end_seconds: float
    configured_end_to_end_budget_seconds: float
    mip_gap_tolerance: float | None
    random_seed: int | None
    threads: int | None
    model_export_enabled: bool
    model_export_path: str | None = None
    solver_parameters: Mapping[str, object] = field(default_factory=dict)
    requested_solver_id: str = "unspecified"

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id cannot be blank.")
        if self.round_index < 0:
            raise ValueError("round_index must be non-negative.")
        _require_nonnegative_finite(self.time_limit_seconds, "time_limit_seconds")
        _require_finite(self.remaining_end_to_end_seconds, "remaining_end_to_end_seconds")
        _require_nonnegative_finite(self.configured_end_to_end_budget_seconds, "configured_end_to_end_budget_seconds")
        if self.mip_gap_tolerance is not None:
            _require_nonnegative_finite(self.mip_gap_tolerance, "mip_gap_tolerance")
        if self.threads is not None and self.threads < 1:
            raise ValueError("threads must be at least one when supplied.")
        if self.model_export_enabled and (self.model_export_path is None or not self.model_export_path.strip()):
            raise ValueError("model_export_path is required when model export is enabled.")
        if not self.requested_solver_id.strip():
            raise ValueError("requested_solver_id cannot be blank.")
        object.__setattr__(self, "solver_parameters", MappingProxyType(dict(self.solver_parameters)))

    @property
    def effective_time_limit_seconds(self) -> float | None:
        """Return the positive time limit the backend should use, or None.

        Return values:
        - None with is_unlimited=True: No time limit (backend runs to completion)
        - None with is_unlimited=False: Budget exhausted, backend should NOT run
        - float > 0: Backend should use this time limit

        Cases:
        - Budget configured (> 0) but exhausted (remaining <= 0): None (don't run)
        - Both unlimited (time_limit=0 and budget=0): None (is_unlimited=True)
        - Timeout unlimited (0), budget finite: remaining budget
        - Timeout finite, budget unlimited (0): timeout
        - Both finite: min(timeout, remaining)
        """
        timeout_unlimited = self.time_limit_seconds == 0
        budget_unlimited = self.configured_end_to_end_budget_seconds == 0

        # Budget is configured but exhausted
        if not budget_unlimited and self.remaining_end_to_end_seconds <= 0:
            return None

        # Both unlimited - signal via None but caller checks is_unlimited
        if timeout_unlimited and budget_unlimited:
            return None

        # Timeout unlimited, use remaining budget
        if timeout_unlimited:
            return self.remaining_end_to_end_seconds

        # Budget unlimited, use timeout
        if budget_unlimited:
            return self.time_limit_seconds

        # Both finite, use minimum
        return min(self.time_limit_seconds, self.remaining_end_to_end_seconds)

    @property
    def is_unlimited(self) -> bool:
        """Return True if no time limit is configured (both timeout and budget are 0)."""
        return self.time_limit_seconds == 0 and self.configured_end_to_end_budget_seconds == 0

    @property
    def is_budget_exhausted(self) -> bool:
        """Return True if the end-to-end budget was configured and is now exhausted."""
        if self.configured_end_to_end_budget_seconds == 0:
            return False  # No budget configured means it cannot be exhausted
        return self.remaining_end_to_end_seconds <= 0

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
    requested_solver_id: str = "unspecified"
    effective_solver_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_finite(self.runtime_seconds, "runtime_seconds")
        if not self.requested_solver_id.strip():
            raise ValueError("requested_solver_id cannot be blank.")
        if self.effective_solver_id is not None and not self.effective_solver_id.strip():
            raise ValueError("effective_solver_id cannot be blank when supplied.")
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
    """Uniform solver boundary for residual classical problems.

    A backend receives a residual problem from the adapter and returns a
    normalized solve result. The problem type is defined by the adapter's
    model provider (e.g., `ClassicalModelProvider`), not by the QReduce
    kernel. The kernel treats the problem as opaque; the backend knows
    how to translate it into solver-specific structures.

    The backend is responsible for:
    - Building solver-specific variables, objective, and constraints
    - Respecting time limits and thread constraints
    - Returning normalized status even on solver errors
    - Exporting the model if requested and supported
    - Including effective parameters in the result for auditability

    The backend does not validate domain semantics: whether the solution
    satisfies fixing requirements and original constraints is checked by
    the adapter's post-check, not by the backend.

    QReduce resolves backend selection by solver ID. An unknown ID is
    a configuration error; a known ID with unavailable binding or license
    produces an explicit failure. There is no silent fallback.
    """

    def solve(
        self, reduced_problem: object, request: ClassicalSolveRequest
    ) -> ClassicalSolveResult:
        """Solve a residual classical problem and return a normalized result.

        Args:
            reduced_problem: The residual problem from the adapter. The
                backend expects a type compatible with its model provider
                (e.g., `ClassicalModelProvider.build_classical_model()`).
            request: Resolved solve parameters including time limit,
                threads, and export settings.

        Returns:
            A normalized result with status, objective, variable values,
            and provenance. The result is produced even for solver errors.

        Note:
            Domain-level validation (fixing compliance, original constraint
            satisfaction) is performed by the adapter's post-check, not
            by the backend.
        """
        ...


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