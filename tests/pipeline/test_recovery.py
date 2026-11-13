"""Tests for the round-local deterministic recovery primitive."""

import pytest

from qreduce.pipeline.recovery import expand_ranked_domain, rank_recovery_items


def test_adds_one_highest_ranked_available_item_per_attempt():
    first = expand_ranked_domain(("a", "b", "c"), ("a",), ("a", "c", "b"), 3)
    assert first == ("a", "c")
    assert expand_ranked_domain(("a", "b", "c"), first, ("a", "c", "b"), 3) == ("a", "c", "b")


def test_cap_and_exhausted_ranking_leave_domain_unchanged():
    assert expand_ranked_domain(("a", "b"), ("a",), ("b",), 1) == ("a",)
    assert expand_ranked_domain(("a", "b"), ("a",), ("a",), 2) == ("a",)


@pytest.mark.parametrize(
    ("input_ids", "retained", "ranked", "cap"),
    [
        (("a",), ("b",), (), 1),
        (("a",), (), ("b",), 1),
        (("a", "a"), (), (), 1),
        (("a",), ("a",), (), 0),
        (("a",), (), (), True),
        (("",), (), (), 1),
    ],
)
def test_rejects_invalid_inputs(input_ids, retained, ranked, cap):
    with pytest.raises(ValueError):
        expand_ranked_domain(input_ids, retained, ranked, cap)


def test_recovery_ranking_preserves_candidate_order_then_weight_and_id():
    assert rank_recovery_items(
        ("a", "b", "c", "d"), ("a",), {"a": 0, "b": 2, "c": 2, "d": 3}
    ) == ("a", "d", "b", "c")


@pytest.mark.parametrize("ranked, weights", [
    (("x",), {"a": 1}),
    ((), {"a": float("nan")}),
    ((), {}),
    (("a", "a"), {"a": 1}),
])
def test_recovery_ranking_rejects_invalid_inputs(ranked, weights):
    with pytest.raises(ValueError):
        rank_recovery_items(("a",), ranked, weights)