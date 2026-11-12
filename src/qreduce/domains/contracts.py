"""Provider-neutral contracts owned by domain adapters."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.mwis import ReductionGraph
from qreduce.solving.residual.contracts import ClassicalSolveResult


@dataclass(frozen=True, slots=True)
class DomainEvaluationMetric:
    """Adapter-supplied numeric evaluation and its externally defined meaning."""

    metric_id: str
    value: float | None
    unit: str
    comparison_convention: str
    provenance: str

    def __post_init__(self) -> None:
        for name in ("metric_id", "unit", "comparison_convention", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-blank string.")
        if self.value is not None and (
            isinstance(self.value, bool)
            or not isinstance(self.value, int | float)
            or not math.isfinite(self.value)
        ):
            raise ValueError("value must be a finite number or None.")

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class LogicalVariableCounts:
    """Logical free variables, excluding explicit fixings and solver auxiliaries."""

    binary_free: int
    integer_free: int
    continuous_free: int

    def __post_init__(self) -> None:
        for name in ("binary_free", "integer_free", "continuous_free"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")

    def to_dict(self) -> dict[str, object]:
        return to_primitive(self)


@dataclass(frozen=True, slots=True)
class DomainValidationResult:
    """Serializable validation result for one proposed candidate domain."""

    is_valid: bool
    minimum_required_items: int | None
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.minimum_required_items is not None and self.minimum_required_items < 0:
            raise ValueError("minimum_required_items must be non-negative when supplied.")
        if self.is_valid and self.failure_reasons:
            raise ValueError("A valid domain result cannot include failure reasons.")
        if not self.is_valid and not self.failure_reasons:
            raise ValueError("An invalid domain result requires at least one failure reason.")

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ProtectionDeclaration:
    """Categorized item protections declared once by an adapter for one round.

    Mandatory, user-locked, and safe-retained items are required protections.
    Incumbent-supported items may instead be best-effort when explicitly requested.
    """

    mandatory_item_ids: tuple[str, ...] = ()
    user_locked_item_ids: tuple[str, ...] = ()
    safe_retained_item_ids: tuple[str, ...] = ()
    incumbent_supported_item_ids: tuple[str, ...] = ()
    incumbent_protection_mode: str = "required"

    def __post_init__(self) -> None:
        categories = (
            "mandatory_item_ids",
            "user_locked_item_ids",
            "safe_retained_item_ids",
            "incumbent_supported_item_ids",
        )
        all_item_ids: list[str] = []
        for category in categories:
            category_value = getattr(self, category)
            if not isinstance(category_value, tuple | list):
                raise TypeError(f"{category} must be a tuple or list of item IDs.")
            item_ids = tuple(category_value)
            if any(not isinstance(item_id, str) or not item_id.strip() for item_id in item_ids):
                raise ValueError(f"{category} must contain non-blank item IDs.")
            if len(set(item_ids)) != len(item_ids):
                raise ValueError(f"{category} must not contain duplicate item IDs.")
            object.__setattr__(self, category, item_ids)
            all_item_ids.extend(item_ids)
        if len(set(all_item_ids)) != len(all_item_ids):
            raise ValueError("An item ID cannot belong to more than one protection category.")
        if self.incumbent_protection_mode not in {"required", "best_effort"}:
            raise ValueError(
                "incumbent_protection_mode must be 'required' or 'best_effort'."
            )

    @property
    def required_item_ids(self) -> tuple[str, ...]:
        """Return categories whose members must survive the candidate-domain cap."""

        incumbent_item_ids = (
            self.incumbent_supported_item_ids
            if self.incumbent_protection_mode == "required"
            else ()
        )
        return (
            self.mandatory_item_ids
            + self.user_locked_item_ids
            + self.safe_retained_item_ids
            + incumbent_item_ids
        )

    @property
    def best_effort_item_ids(self) -> tuple[str, ...]:
        """Return incumbent items that may be excluded when the cap requires it."""

        return (
            self.incumbent_supported_item_ids
            if self.incumbent_protection_mode == "best_effort"
            else ()
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FixingEntry:
    """Explicit values that a domain adapter requires for one excluded item."""

    item_id: str
    variable_values: Mapping[str, float]
    reason: str

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("item_id cannot be blank.")
        if not self.reason.strip():
            raise ValueError("reason cannot be blank.")
        values = dict(self.variable_values)
        if not values or any(not variable_name.strip() for variable_name in values):
            raise ValueError("variable_values must contain non-blank variable names.")
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("variable_values must contain finite values.")
        object.__setattr__(self, "variable_values", MappingProxyType(values))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FixingManifest:
    """Complete, auditable fixing decisions derived from a candidate domain."""

    retained_item_ids: tuple[str, ...]
    excluded_item_ids: tuple[str, ...]
    entries: tuple[FixingEntry, ...]
    origin: str
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        retained = tuple(self.retained_item_ids)
        excluded = tuple(self.excluded_item_ids)
        if len(set(retained)) != len(retained) or len(set(excluded)) != len(excluded):
            raise ValueError("Retained and excluded item IDs must each be unique.")
        if set(retained) & set(excluded):
            raise ValueError("Retained and excluded item IDs must not overlap.")
        if not self.origin.strip():
            raise ValueError("origin cannot be blank.")
        entry_item_ids = tuple(entry.item_id for entry in self.entries)
        if len(set(entry_item_ids)) != len(entry_item_ids):
            raise ValueError("Fixing manifest entries must be unique per item.")
        if set(entry_item_ids) != set(excluded):
            raise ValueError("Fixing manifest entries must cover exactly the excluded items.")
        object.__setattr__(self, "retained_item_ids", retained)
        object.__setattr__(self, "excluded_item_ids", excluded)
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FinalSolutionValidationResult:
    """Independent domain validation of a residual classical solution."""

    postcheck_feasible: bool
    fixed_variable_compliance: bool
    original_constraint_compliance: bool
    integrality_compliance: bool
    objective_recomputed: float | None
    solver_objective_compliance: bool | None
    failure_reasons: tuple[str, ...] = ()
    tolerances_used: Mapping[str, float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.postcheck_feasible and self.failure_reasons:
            raise ValueError("A passed post-check cannot include failure reasons.")
        if not self.postcheck_feasible and not self.failure_reasons:
            raise ValueError("A failed post-check requires at least one failure reason.")
        object.__setattr__(self, "failure_reasons", tuple(self.failure_reasons))
        object.__setattr__(self, "tolerances_used", MappingProxyType(dict(self.tolerances_used)))

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


class ReducibleProblemAdapter(Protocol):
    """Minimum boundary between the provider-neutral kernel and a domain model."""

    def describe_logical_variables(self, problem: object) -> LogicalVariableCounts: ...

    def evaluate_domain_metrics(
        self, problem: object, classical_result: ClassicalSolveResult,
        postcheck_result: FinalSolutionValidationResult,
    ) -> tuple[DomainEvaluationMetric, ...]: ...

    def identify_reducible_items(self, problem: object) -> list[str]: ...

    def build_conflict_graph(self, problem: object, state: object | None = None) -> ReductionGraph: ...

    def declare_protected_items(
        self, problem: object
    ) -> tuple[str, ...] | ProtectionDeclaration: ...

    def validate_candidate_domain(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult: ...

    def build_fixing_manifest(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
    ) -> FixingManifest: ...

    def restrict_problem(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
        fixing_manifest: FixingManifest,
    ) -> object: ...

    def validate_final_solution(
        self,
        original_problem: object,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: object,
        solver_objective_value: float | None = None,
    ) -> FinalSolutionValidationResult: ...