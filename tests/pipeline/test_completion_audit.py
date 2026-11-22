"""Regression coverage for repair/completion provenance and final candidates."""

from types import SimpleNamespace

import pytest

from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.pipeline.single_pass import (
    _build_completion_policy,
    _candidate_records,
    _select_diverse_samples_with_audit,
    _valid_or_repaired_samples,
)
from qreduce.solving.mwis import RawMISSample, deduplicate_raw_mis_samples
from qreduce.solving.mwis.completion import (
    complete_candidate,
    greedy_weight_completion_policy,
)


def fixtures():
    graph = ReductionGraph(
        ("a", "b", "c"), {"a": 2., "b": 1., "c": 3.},
        (("a", "b"),), {("a", "b"): "conflict"}, "test", "1",
    )
    qubo = build_mwis_qubo(graph, 4)
    problem = CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))
    config = SimpleNamespace(
        mis_execution=SimpleNamespace(completion_enabled=True, completion_policy_id="greedy_by_weight",
                                      repair_enabled=True, repair_max_iterations=2,
                                      minimum_candidate_jaccard_distance=0),
        reduction=SimpleNamespace(num_source_mis_candidates=2),
    )
    return problem, config


def test_completion_has_separate_audit_and_preserves_sources():
    problem, config = fixtures()
    samples = (
        RawMISSample("s0", problem.graph.node_ids, (1, 0, 0), is_independent_set=True,
                     canonical_qubo_energy=-2., selection_weight=2., num_selected=1),
        RawMISSample("s1", problem.graph.node_ids, (1, 0, 1), is_independent_set=True,
                     canonical_qubo_energy=-5., selection_weight=5., num_selected=2),
    )
    processed = _valid_or_repaired_samples(problem, samples, config)
    unique = deduplicate_raw_mis_samples(processed, 2).samples
    assert len(unique) == 1
    assert set(unique[0].source_raw_sample_ids) == {"s0", "s1"}
    selected, reasons = _select_diverse_samples_with_audit(unique, config)
    reasons = {**reasons, "s1": "duplicate_after_processing"}
    records = _candidate_records(problem, samples, (), processed, selected, reasons, config)
    first = records[0]
    assert first.repair_status == "valid_without_repair"
    assert first.energy_recomputed_after_repair is None
    assert first.completion_applied
    assert first.completion_actions == ("added_item:c",)
    assert first.energy_after_completion == -5.
    assert set(first.source_raw_sample_ids) == {"s0", "s1"}
    assert records[1].rejection_reason == "duplicate_after_processing"


def test_repair_and_completion_remain_distinct():
    problem, config = fixtures()
    raw = RawMISSample("s", problem.graph.node_ids, (1, 1, 0), is_independent_set=False)
    processed = _valid_or_repaired_samples(problem, (raw,), config)
    records = _candidate_records(problem, (raw,), (), processed, processed, {}, config)
    assert records[0].repair_actions == ("removed_item:b",)
    assert records[0].completion_actions == ("added_item:c",)
    assert records[0].energy_recomputed_after_repair == -2.


@pytest.mark.parametrize("policy", ["disabled", "typo"])
def test_invalid_completion_policy_is_not_silently_enabled(policy):
    _, config = fixtures()
    config.mis_execution.completion_policy_id = policy
    with pytest.raises(ValueError):
        _build_completion_policy(config)


def test_completion_rejects_nonbinary_input():
    problem, _ = fixtures()
    with pytest.raises(ValueError):
        complete_candidate(problem.graph, (2, 0, 0), greedy_weight_completion_policy())