"""Provider-neutral contracts owned by domain adapters."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from qreduce.artifacts.metadata import redact_metadata, to_primitive
from qreduce.mwis import ReductionGraph


@dataclass(frozen=True, slots=True)
class DomainValidationResult:
    """Serializable domain precheck result for a proposed candidate domain.

    ``protected_items`` declares IDs that the pipeline must retain before it
    applies the candidate-domain cap. Declared IDs must belong to the round's
    canonical reduction graph.
    """

    is_valid: bool
    minimum_required_items: int | None
    protected_items: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.minimum_required_items is not None and self.minimum_required_items < 0:
            raise ValueError("minimum_required_items must be non-negative when supplied.")
        if len(set(self.protected_items)) != len(self.protected_items):
            raise ValueError("protected_items must be unique.")
        if self.is_valid and self.failure_reasons:
            raise ValueError("A valid domain result cannot include failure reasons.")
        if not self.is_valid and not self.failure_reasons:
            raise ValueError("An invalid domain result requires at least one failure reason.")

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

    def identify_reducible_items(self, problem: object) -> list[str]: ...

    def build_conflict_graph(self, problem: object, state: object | None = None) -> ReductionGraph: ...

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