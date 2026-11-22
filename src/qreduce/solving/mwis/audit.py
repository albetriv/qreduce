"""Audit contracts for MWIS result transparency.

This module defines the three-level audit structure for MWIS results:

1. Raw Sample Level: Backend output without any post-processing.
2. Validated Candidate Level: Sample after validation, repair, and
   optional classical completion.
3. Final Domain Level: Retained items after aggregation, protection
   rules, and configured caps.

Each level has distinct provenance and guarantees. The contracts ensure
that transformations between levels are traceable and that no level
claims properties that belong to a different level.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from qreduce.artifacts.metadata import redact_metadata, to_primitive


class IndependenceStatus(StrEnum):
    """Whether a selection forms an independent set."""

    VERIFIED_INDEPENDENT = "verified_independent"
    REPAIRED_TO_INDEPENDENT = "repaired_to_independent"
    NOT_INDEPENDENT = "not_independent"
    NOT_VERIFIED = "not_verified"


class MaximalityStatus(StrEnum):
    """Whether an independent set is maximal (no node can be added)."""

    VERIFIED_MAXIMAL = "verified_maximal"
    COMPLETED_TO_MAXIMAL = "completed_to_maximal"
    NOT_MAXIMAL = "not_maximal"
    NOT_VERIFIED = "not_verified"


class OptimalityClaim(StrEnum):
    """Strength of optimality claim for a solution."""

    CERTIFIED_OPTIMAL = "certified_optimal"  # Proven globally optimal
    EXACT_PRESOLVE = "exact_presolve"  # Trivially optimal (e.g., edgeless)
    GAP_BOUNDED = "gap_bounded"  # Within known gap of optimal
    HEURISTIC_BEST = "heuristic_best"  # Best found, no optimality proof
    NOT_CLAIMED = "not_claimed"  # No optimality claim made


class WeightEncodingMode(StrEnum):
    """How MWIS weights are represented in the backend execution."""

    PHYSICALLY_ENCODED = "physically_encoded"  # Weights in Hamiltonian
    CLASSICAL_RANKING = "classical_ranking"  # Weights only for ranking
    NOT_APPLICABLE = "not_applicable"  # E.g., exact presolve


@dataclass(frozen=True, slots=True)
class RawSampleAudit:
    """Audit information for a raw backend sample.

    This captures the sample exactly as returned by the backend, before
    any validation, repair, or completion. The fields describe what the
    backend produced, not what we computed afterward.
    """

    raw_sample_id: str
    source_provider_id: str
    source_backend_id: str
    backend_reported_score: float | None
    backend_reported_score_kind: str
    occurrence_count: int
    execution_runtime_seconds: float | None
    independence_at_emission: IndependenceStatus
    weight_encoding_mode: WeightEncodingMode
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ValidatedCandidateAudit:
    """Audit information for a validated and possibly repaired candidate.

    This level represents a sample after:
    1. Independence verification (is_independent_set computed)
    2. Repair if necessary (violated edges resolved)
    3. Optional classical completion (maximize selection)

    The fields distinguish between properties from the raw sample and
    properties acquired through post-processing.
    """

    candidate_id: str
    source_raw_sample_ids: tuple[str, ...]
    independence_status: IndependenceStatus
    maximality_status: MaximalityStatus
    optimality_claim: OptimalityClaim

    # Weight metrics
    selection_weight_raw: float | None  # Weight before repair/completion
    selection_weight_final: float  # Weight after all processing
    weight_improvement: float  # Final - raw (0 if no processing)

    # Selection metrics
    num_selected_raw: int | None
    num_selected_final: int
    nodes_removed_by_repair: tuple[str, ...] = ()
    nodes_added_by_completion: tuple[str, ...] = ()

    # Processing trace
    repair_applied: bool = False
    completion_applied: bool = False
    completion_policy_id: str | None = None

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_raw_sample_ids", tuple(self.source_raw_sample_ids)
        )
        object.__setattr__(
            self, "nodes_removed_by_repair", tuple(self.nodes_removed_by_repair)
        )
        object.__setattr__(
            self, "nodes_added_by_completion", tuple(self.nodes_added_by_completion)
        )
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FinalDomainAudit:
    """Audit information for the final retained domain.

    This level represents the domain after:
    1. Aggregation across selected candidates
    2. Protection rules applied (required/best-effort items)
    3. Domain cap enforced (candidate_domain_max_items)

    The fields separate the contributions from MWIS solving versus
    configuration constraints.
    """

    # Size metrics at each stage
    candidate_union_size: int  # Items in union of selected candidates
    after_protection_size: int  # After adding protected items
    final_domain_size: int  # After applying cap

    # Breakdown of exclusions
    excluded_by_mwis: int  # Not selected by any candidate
    excluded_by_cap: int  # Removed to meet cap
    protected_required_count: int  # Required items added
    protected_best_effort_count: int  # Best-effort items added

    # Weight metrics
    total_weight_before_cap: float
    total_weight_after_cap: float
    weight_lost_to_cap: float

    # Optimality degradation
    optimality_before_cap: OptimalityClaim
    optimality_after_cap: OptimalityClaim
    cap_caused_degradation: bool

    # Source candidates
    source_candidate_ids: tuple[str, ...] = ()

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_candidate_ids", tuple(self.source_candidate_ids)
        )
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class MWISAuditSummary:
    """Complete audit trail from raw samples to final domain.

    This aggregates the three audit levels into a single structure
    for artifact serialization and comparison display.
    """

    # Level summaries
    raw_sample_count: int
    unique_sample_count: int
    valid_candidate_count: int
    selected_candidate_count: int

    # Best candidate metrics (before domain aggregation)
    best_candidate_weight: float | None
    best_candidate_size: int | None
    best_candidate_optimality: OptimalityClaim

    # Final domain metrics
    final_domain_size: int
    final_domain_weight: float

    # Presolve information
    presolve_applied: bool = False
    presolve_reason: str | None = None

    # Processing flags
    any_repair_applied: bool = False
    any_completion_applied: bool = False

    # Detailed audits (optional, for full artifact)
    raw_sample_audits: tuple[RawSampleAudit, ...] = ()
    candidate_audits: tuple[ValidatedCandidateAudit, ...] = ()
    domain_audit: FinalDomainAudit | None = None

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "raw_sample_audits", tuple(self.raw_sample_audits)
        )
        object.__setattr__(
            self, "candidate_audits", tuple(self.candidate_audits)
        )
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]
