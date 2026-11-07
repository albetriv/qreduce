"""Canonical MIS sample normalization and deterministic deduplication."""

from collections import defaultdict

from qreduce.mis.contracts import (
    DeduplicationResult,
    MISBackendResult,
    MISNormalizationResult,
    RawMISSample,
)
from qreduce.mwis.energy import ising_energy, qubo_energy
from qreduce.mwis.graph import CanonicalMWISProblem
from qreduce.mwis.ising import delta_to_spin
from qreduce.mwis.validation import MWISValidationError, validate_binary_selection
from qreduce.status import TerminalReason


def normalize_backend_result(
    problem: CanonicalMWISProblem,
    backend_result: MISBackendResult,
) -> MISNormalizationResult:
    """Recompute canonical metrics while preserving native score semantics and raw metadata."""

    normalized_samples: list[RawMISSample] = []
    try:
        for sample in backend_result.samples:
            if sample.node_order != problem.graph.node_ids:
                raise MWISValidationError(
                    "node_order_mismatch",
                    "sample.node_order",
                    "Sample node order does not match canonical graph order.",
                )
            validation = validate_binary_selection(problem.graph, sample.delta)
            normalized_samples.append(
                RawMISSample(
                    raw_sample_id=sample.raw_sample_id,
                    node_order=sample.node_order,
                    delta=sample.delta,
                    occurrence_count=sample.occurrence_count,
                    backend_reported_score=sample.backend_reported_score,
                    backend_reported_score_kind=sample.backend_reported_score_kind,
                    canonical_qubo_energy=qubo_energy(problem.qubo, sample.delta),
                    canonical_ising_energy=ising_energy(problem.ising, delta_to_spin(sample.delta)),
                    selection_weight=validation.selection_weight,
                    num_selected=validation.num_selected,
                    is_independent_set=validation.is_independent_set,
                    violated_edges=validation.violated_edges,
                    num_violated_edges=validation.num_violated_edges,
                    source_provider_id=sample.source_provider_id,
                    source_backend_id=sample.source_backend_id,
                    execution_runtime_seconds=sample.execution_runtime_seconds,
                    effective_compilation_parameters=sample.effective_compilation_parameters,
                    effective_execution_parameters=sample.effective_execution_parameters,
                    raw_backend_metadata=sample.raw_backend_metadata,
                    source_raw_sample_ids=sample.source_raw_sample_ids,
                )
            )
    except (MWISValidationError, ValueError) as error:
        return MISNormalizationResult(
            samples=tuple(normalized_samples),
            terminal_reason=TerminalReason.MIS_RESULT_NORMALIZATION_FAILED,
            diagnostic_message=str(error),
        )
    return MISNormalizationResult(samples=tuple(normalized_samples))


def deduplicate_raw_mis_samples(
    samples: tuple[RawMISSample, ...],
    max_distinct_samples: int,
) -> DeduplicationResult:
    """Aggregate equal delta vectors, choose stable IDs, then enforce a deterministic cap."""

    if not isinstance(max_distinct_samples, int) or isinstance(max_distinct_samples, bool) or max_distinct_samples < 1:
        raise ValueError("max_distinct_samples must be an integer greater than zero.")
    grouped_samples: dict[tuple[int, ...], list[RawMISSample]] = defaultdict(list)
    for sample in samples:
        grouped_samples[sample.delta].append(sample)
    aggregate_samples: list[RawMISSample] = []
    for delta, group in grouped_samples.items():
        representative = min(group, key=lambda sample: sample.raw_sample_id)
        source_ids = tuple(sorted({source_id for sample in group for source_id in sample.source_raw_sample_ids}))
        aggregate_samples.append(
            RawMISSample(
                raw_sample_id=representative.raw_sample_id,
                node_order=representative.node_order,
                delta=delta,
                occurrence_count=sum(sample.occurrence_count for sample in group),
                backend_reported_score=representative.backend_reported_score,
                backend_reported_score_kind=representative.backend_reported_score_kind,
                canonical_qubo_energy=representative.canonical_qubo_energy,
                canonical_ising_energy=representative.canonical_ising_energy,
                selection_weight=representative.selection_weight,
                num_selected=representative.num_selected,
                is_independent_set=representative.is_independent_set,
                violated_edges=representative.violated_edges,
                num_violated_edges=representative.num_violated_edges,
                source_provider_id=representative.source_provider_id,
                source_backend_id=representative.source_backend_id,
                execution_runtime_seconds=representative.execution_runtime_seconds,
                effective_compilation_parameters=representative.effective_compilation_parameters,
                effective_execution_parameters=representative.effective_execution_parameters,
                raw_backend_metadata=representative.raw_backend_metadata,
                source_raw_sample_ids=source_ids,
            )
        )
    ordered_samples = tuple(sorted(aggregate_samples, key=lambda sample: (sample.delta, sample.raw_sample_id)))
    return DeduplicationResult(
        samples=ordered_samples[:max_distinct_samples],
        discarded_samples=ordered_samples[max_distinct_samples:],
    )