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
    fixing_origin: str = "mis_heuristic"
    guarantee_level: str = "heuristic"
    proof_reference: str | None = None
    user_request_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("item_id cannot be blank.")
        if not self.reason.strip():
            raise ValueError("reason cannot be blank.")
        if self.fixing_origin not in {"mis_heuristic", "certified_rule", "user_mandated"}:
            raise ValueError("Invalid fixing origin.")
        if self.guarantee_level not in {"heuristic", "safe", "user_imposed"}:
            raise ValueError("Invalid fixing guarantee level.")
        if self.guarantee_level == "safe" and (
            not isinstance(self.proof_reference, str) or not self.proof_reference.strip()
        ):
            raise ValueError("A safe fixing requires a proof reference.")
        if self.fixing_origin == "mis_heuristic" and self.guarantee_level != "heuristic":
            raise ValueError("A MIS heuristic fixing cannot claim safety or user imposition.")
        if self.guarantee_level == "user_imposed" and self.fixing_origin != "user_mandated":
            raise ValueError("A user-imposed fixing requires user-mandated origin.")
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
    round_index: int = 0
    source_candidate_ids: tuple[str, ...] = ()
    policy_version: str | None = None

    def __post_init__(self) -> None:
        retained = tuple(self.retained_item_ids)
        excluded = tuple(self.excluded_item_ids)
        if len(set(retained)) != len(retained) or len(set(excluded)) != len(excluded):
            raise ValueError("Retained and excluded item IDs must each be unique.")
        if set(retained) & set(excluded):
            raise ValueError("Retained and excluded item IDs must not overlap.")
        if not self.origin.strip():
            raise ValueError("origin cannot be blank.")
        if not isinstance(self.round_index, int) or isinstance(self.round_index, bool) or self.round_index < 0:
            raise ValueError("round_index must be a non-negative integer.")
        if any(not isinstance(value, str) or not value.strip() for value in self.source_candidate_ids):
            raise ValueError("source_candidate_ids must be non-blank strings.")
        entry_item_ids = tuple(entry.item_id for entry in self.entries)
        if len(set(entry_item_ids)) != len(entry_item_ids):
            raise ValueError("Fixing manifest entries must be unique per item.")
        if set(entry_item_ids) != set(excluded):
            raise ValueError("Fixing manifest entries must cover exactly the excluded items.")
        object.__setattr__(self, "retained_item_ids", retained)
        object.__setattr__(self, "excluded_item_ids", excluded)
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "source_candidate_ids", tuple(self.source_candidate_ids))
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
    """Boundary between the provider-neutral QReduce kernel and a domain model.

    An adapter translates between domain-specific semantics and QReduce's
    reduction pipeline. Each method corresponds to a phase in the pipeline;
    the kernel calls them in a defined order and expects consistent results.

    The adapter owns the domain model and decides how to map reducible items
    to graph nodes, how to fix excluded variables, and how to validate
    solutions. QReduce does not inspect or modify the domain problem directly.

    Implementations must be stateless between calls: the kernel may invoke
    methods on fresh adapter instances. State across phases is passed
    explicitly via method arguments.

    Adapter failures (exceptions, invalid returns) are captured by the kernel
    and normalized. Most adapter exceptions produce `adapter_failure` status;
    graph construction exceptions produce `GRAPH_CONSTRUCTION_FAILED` to
    distinguish graph-specific failures. Previous results are preserved;
    the failing phase's output is not adopted.
    """

    def describe_logical_variables(self, problem: object) -> LogicalVariableCounts:
        """Count logical free variables in the problem, excluding fixings.

        Called by the kernel early in the pipeline to record the original
        problem size. Called again after restriction to record the residual
        size. The counts exclude variables already fixed by the adapter and
        auxiliary variables introduced by solvers.

        Args:
            problem: The domain problem (original or residual).

        Returns:
            Counts of binary, integer, and continuous free variables.

        Raises:
            Exception: Any exception produces adapter_failure; the kernel
                preserves prior results without adopting this phase's output.

        Note:
            The method does not require solving to compute counts. Implicit
            fixings deduced by solvers are not reflected here.
        """
        ...

    def evaluate_domain_metrics(
        self,
        problem: object,
        classical_result: ClassicalSolveResult,
        postcheck_result: FinalSolutionValidationResult,
    ) -> tuple[DomainEvaluationMetric, ...]:
        """Compute domain-specific quality metrics after post-check completion.

        Called when the post-check has been reached and returned a valid
        result, regardless of whether the post-check passed or failed.
        The adapter may return an empty tuple if no metrics are defined
        or if the metrics are not meaningful for a failed post-check.

        Each metric includes value, unit, comparison convention, and
        provenance for auditability.

        Args:
            problem: The original domain problem.
            classical_result: The result of the classical residual solve.
            postcheck_result: The validation result (may be passed or failed).

        Returns:
            A tuple of domain metrics, possibly empty. Each metric is
            independently serializable.

        Raises:
            Exception: Any exception produces adapter_failure; the solution
                is not adopted, but solve and fixing results are preserved.

        Note:
            This method is not called when the post-check was not reached
            (e.g., classical solve failed). In that case, the result field
            is None.
        """
        ...

    def identify_reducible_items(self, problem: object) -> list[str]:
        """List all item IDs eligible for reduction.

        Called before graph construction. The returned IDs define the
        universe of items that may appear as graph nodes. Items not listed
        here cannot be reduced or protected.

        Args:
            problem: The domain problem.

        Returns:
            A list of unique, non-blank item IDs. Order is not significant.

        Raises:
            Exception: Any exception produces adapter_failure.

        Note:
            The kernel does not validate IDs against domain semantics. The
            adapter must ensure IDs are consistent across all methods.
        """
        ...

    def build_conflict_graph(
        self, problem: object, state: object | None = None
    ) -> ReductionGraph:
        """Construct the MWIS graph encoding conflicts and preferences.

        Called after identifying reducible items. The graph defines nodes
        (items with weights) and edges (conflicts or redundancies). The
        kernel uses this graph to formulate the MWIS problem.

        Node weights express preference for retaining items. Edge semantics
        depend on the adapter's policy: edges may represent hard conflicts,
        redundancies, or correlation-based exclusions. The adapter documents
        its policy; the kernel treats all edges uniformly as MWIS constraints.

        Args:
            problem: The domain problem.
            state: Optional adapter-defined state from a prior round.
                Reserved for future incremental graph updates. Currently
                the pipeline does not pass state between rounds; this
                parameter always receives its default value (None).

        Returns:
            A ReductionGraph with nodes for reducible items and edges
            encoding the adapter's conflict/redundancy policy.

        Raises:
            Exception: Exceptions during graph construction produce
                GRAPH_CONSTRUCTION_FAILED (not adapter_failure). The
                distinction allows the kernel to identify graph-specific
                failures separately from other adapter errors.

        Note:
            The graph is auxiliary: its edges are not constraints of the
            original problem. MWIS selects items to retain, not the final
            solution.
        """
        ...

    def declare_protected_items(
        self, problem: object,
    ) -> tuple[str, ...] | ProtectionDeclaration:
        """Declare items that should survive reduction, with varying guarantees.

        Called before candidate domain validation. Protection categories
        have different guarantees:

        - **Required** (mandatory, user-locked, safe-retained): guaranteed
          to appear in the retained set. If required protections exceed
          the candidate-domain cap, reduction fails explicitly.
        - **Best-effort** (incumbent-supported with best_effort mode): may
          be excluded when the cap requires it.

        A simple tuple of IDs is equivalent to mandatory (required)
        protection. ProtectionDeclaration allows finer categorization.

        Args:
            problem: The domain problem.

        Returns:
            Either a tuple of item IDs (mandatory protection) or a
            ProtectionDeclaration with categorized protections.

        Raises:
            Exception: Any exception produces adapter_failure.

        Note:
            Protected items count against the candidate-domain cap. Only
            required protections are guaranteed; best-effort items may be
            sacrificed to respect the cap.
        """
        ...

    def validate_candidate_domain(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
    ) -> DomainValidationResult:
        """Validate a proposed candidate domain before fixing.

        Called after MWIS selection and repair. The adapter verifies that
        the retained items form a valid reducible domain: sufficient
        coverage, no missing dependencies, etc.

        Args:
            problem: The domain problem.
            retained_item_ids: The proposed items to retain.

        Returns:
            A validation result with is_valid, optional minimum_required_items,
            and failure_reasons if invalid.

        Raises:
            Exception: Any exception produces adapter_failure.

        Note:
            If invalid (is_valid=False) or the retained count is below
            minimum_required_items, the kernel produces CANDIDATE_DOMAIN_TOO_SMALL.
            Recovery may then be attempted depending on the configured
            recovery_policy_on_domain_too_small and the remaining recovery
            budget, regardless of whether minimum_required_items was provided.
        """
        ...

    def build_fixing_manifest(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
    ) -> FixingManifest:
        """Build explicit variable fixings for excluded items.

        Called after candidate domain validation succeeds. The adapter
        decides how to fix variables for items not in the retained set.
        Each fixing entry includes origin and guarantee level for
        auditability.

        Args:
            problem: The domain problem.
            retained_item_ids: The validated items to retain.

        Returns:
            A FixingManifest covering exactly the excluded items, with
            entries specifying variable values and their provenance.

        Raises:
            Exception: Any exception produces adapter_failure.

        Note:
            The manifest distinguishes MIS heuristic fixings (no optimality
            guarantee), certified safe fixings (with proof reference), and
            user-mandated fixings. The kernel records this provenance.
        """
        ...

    def restrict_problem(
        self,
        problem: object,
        retained_item_ids: tuple[str, ...],
        fixing_manifest: FixingManifest,
    ) -> object:
        """Create the residual problem by applying fixings.

        Called after building the fixing manifest. The adapter produces a
        new problem instance with the excluded variables fixed according
        to the manifest. The residual problem is then solved by the
        classical backend.

        The original problem must remain unmodified.

        Args:
            problem: The original domain problem (unmodified).
            retained_item_ids: Items to keep free.
            fixing_manifest: Explicit fixings for excluded items.

        Returns:
            A new residual problem instance suitable for classical solving.
            The return type is domain-specific and opaque to the kernel.

        Raises:
            Exception: Any exception produces adapter_failure.

        Note:
            The residual problem may have a different structure than the
            original (fewer variables, simplified constraints). The adapter
            must ensure the classical backend can solve it.
        """
        ...

    def validate_final_solution(
        self,
        original_problem: object,
        solution: object,
        fixing_manifest: FixingManifest,
        tolerances: object,
        solver_objective_value: float | None = None,
    ) -> FinalSolutionValidationResult:
        """Validate the residual solution against the original problem.

        Called after classical solve succeeds. The adapter performs an
        independent post-check: verifying fixed variable compliance,
        original constraint satisfaction, integrality, and optionally
        objective consistency.

        Args:
            original_problem: The unmodified domain problem.
            solution: The solution returned by the classical solver.
            fixing_manifest: The fixings applied during restriction.
            tolerances: Domain-specific numerical tolerances.
            solver_objective_value: The objective reported by the solver,
                if available. None if the solver did not report one.

        Returns:
            A validation result with compliance flags, recomputed objective,
            failure reasons if any, and tolerances used.

        Raises:
            Exception: Any exception produces adapter_failure; the solution
                is not adopted, but solve and fixing results are preserved.

        Note:
            A failed post-check does not invalidate the experiment: the
            failure is recorded and the run is published as analyzable.
            The adapter should not raise for validation failures; it should
            return a result with postcheck_feasible=False and reasons.
        """
        ...