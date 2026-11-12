"""Tests for deterministic candidate selection helpers used by the single-pass pipeline."""

from types import SimpleNamespace

from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.pipeline.single_pass import (
    _candidate_domain_item_ids,
    _candidate_records,
    _repair_sample,
    _select_diverse_samples,
    _select_diverse_samples_with_audit,
)
from qreduce.solving.mwis.contracts import RawMISSample


def make_selection_config() -> SimpleNamespace:
    """Build only the configuration fields consumed by candidate helper tests."""

    return SimpleNamespace(
        reduction=SimpleNamespace(
            candidate_domain_max_items=1, num_source_mis_candidates=2
        ),
        mis_execution=SimpleNamespace(
            minimum_candidate_jaccard_distance=0.5,
            repair_enabled=True,
            repair_max_iterations=1,
        ),
    )


def make_problem() -> CanonicalMWISProblem:
    """Build a graph exercising repair tie-breakers and candidate aggregation."""

    graph = ReductionGraph(
        node_ids=("a", "b", "c"),
        node_weights={"a": 1.0, "b": 1.0, "c": 2.0},
        edges=(("a", "b"), ("b", "c")),
        edge_reasons={("a", "b"): "conflict", ("b", "c"): "conflict"},
        graph_policy_id="test",
        graph_policy_version="1",
    )
    qubo = build_mwis_qubo(graph, 3.0)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def test_repair_removes_lexically_larger_endpoint_after_weight_and_degree_ties() -> (
    None
):
    """The repair rule removes b from the equal-weight, equal-degree violated edge a-b."""

    problem = make_problem()
    repaired = _repair_sample(
        problem,
        RawMISSample("raw", problem.graph.node_ids, (1, 1, 0)),
        repair_max_iterations=1,
    )

    assert repaired is not None
    assert repaired.delta == (1, 0, 0)
    assert repaired.is_independent_set is True
    assert repaired.selection_weight == 1.0


def test_diversity_ranking_and_domain_cap_use_declared_keys() -> None:
    """Higher-ranked candidates are selected only when sufficiently distant, then item cap is enforced."""

    problem = make_problem()
    config = make_selection_config()
    samples = (
        RawMISSample(
            "candidate-b",
            problem.graph.node_ids,
            (1, 0, 0),
            canonical_qubo_energy=-1.0,
            selection_weight=1.0,
            num_selected=1,
            is_independent_set=True,
        ),
        RawMISSample(
            "candidate-a",
            problem.graph.node_ids,
            (0, 0, 1),
            canonical_qubo_energy=-2.0,
            selection_weight=2.0,
            num_selected=1,
            is_independent_set=True,
        ),
        RawMISSample(
            "duplicate",
            problem.graph.node_ids,
            (0, 0, 1),
            canonical_qubo_energy=-2.0,
            selection_weight=2.0,
            num_selected=1,
            is_independent_set=True,
        ),
    )

    selected = _select_diverse_samples(samples, config)
    retained = _candidate_domain_item_ids(
        problem.graph.node_ids, problem.graph.node_weights, selected, config
    )

    assert tuple(sample.raw_sample_id for sample in selected) == (
        "candidate-a",
        "candidate-b",
    )
    assert retained == ("c",)


def test_candidate_domain_protection_precedes_cap_in_canonical_order() -> None:
    """Protected IDs survive the cap before ranked MWIS-derived items are considered."""

    problem = make_problem()
    config = make_selection_config()
    samples = (
        RawMISSample(
            "candidate",
            problem.graph.node_ids,
            (0, 0, 1),
            canonical_qubo_energy=-2.0,
            selection_weight=2.0,
            num_selected=1,
            is_independent_set=True,
        ),
    )

    retained = _candidate_domain_item_ids(
        problem.graph.node_ids,
        problem.graph.node_weights,
        samples,
        config,
        protected_item_ids=("b",),
    )

    assert retained == ("b",)


def test_diversity_audit_records_the_observed_rejection_reason() -> None:
    """A diversity rejection is retained rather than inferred from the final sample set."""

    problem = make_problem()
    config = make_selection_config()
    samples = (
        RawMISSample(
            "best",
            problem.graph.node_ids,
            (0, 0, 1),
            canonical_qubo_energy=-2.0,
            selection_weight=2.0,
            num_selected=1,
            is_independent_set=True,
        ),
        RawMISSample(
            "too-close",
            problem.graph.node_ids,
            (0, 0, 1),
            canonical_qubo_energy=-2.0,
            selection_weight=2.0,
            num_selected=1,
            is_independent_set=True,
        ),
    )

    selected, rejection_reasons = _select_diverse_samples_with_audit(samples, config)

    assert tuple(sample.raw_sample_id for sample in selected) == ("best",)
    assert rejection_reasons == {"too-close": "insufficient_jaccard_distance"}


def test_candidate_records_retain_repair_and_distinct_sample_cap_outcomes() -> None:
    """Every processed or distinct-sample-cap discard remains visible in the candidate audit."""

    problem = make_problem()
    config = make_selection_config()
    invalid = RawMISSample(
        "invalid",
        problem.graph.node_ids,
        (1, 1, 0),
        canonical_qubo_energy=1.0,
        selection_weight=2.0,
        num_selected=2,
        is_independent_set=False,
        num_violated_edges=1,
    )
    repaired = _repair_sample(problem, invalid, repair_max_iterations=1)
    assert repaired is not None

    records = _candidate_records(
        problem,
        (invalid,),
        (RawMISSample("discarded", problem.graph.node_ids, (0, 0, 1)),),
        (repaired,),
        (repaired,),
        {},
        config,
    )

    assert records[0].repair_status == "repaired"
    assert records[0].repair_actions == ("removed_item:b",)
    assert records[0].num_violated_edges_before_repair == 1
    assert records[0].selection_status == "selected"
    assert records[1].repair_status == "not_processed_after_deduplication"
    assert records[1].rejection_reason == "max_distinct_samples_limit"


def test_best_effort_protection_can_be_excluded_by_the_candidate_domain_cap() -> None:
    """Best-effort incumbent items compete under the cap instead of becoming mandatory."""

    problem = make_problem()
    config = make_selection_config()
    sample = RawMISSample(
        "candidate",
        problem.graph.node_ids,
        (0, 0, 1),
        canonical_qubo_energy=-2.0,
        selection_weight=2.0,
        num_selected=1,
        is_independent_set=True,
    )

    retained = _candidate_domain_item_ids(
        problem.graph.node_ids,
        problem.graph.node_weights,
        (sample,),
        config,
        best_effort_item_ids=("a",),
    )

    assert retained == ("c",)
