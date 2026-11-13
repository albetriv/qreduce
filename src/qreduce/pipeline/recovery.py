"""Deterministic, round-local candidate-domain recovery primitives."""

import math
from collections.abc import Mapping, Sequence


def rank_recovery_items(
    input_item_ids: Sequence[str],
    ranked_candidate_item_ids: Sequence[str],
    node_weights: Mapping[str, float],
) -> tuple[str, ...]:
    """Extend candidate ranking with unseen items by descending weight, then ID.

    This order is for recovery only and does not change the candidate domain.
    """
    items = tuple(input_item_ids)
    ranked = tuple(ranked_candidate_item_ids)
    if any(not isinstance(item, str) or not item.strip() for item in (*items, *ranked)):
        raise ValueError("Item IDs must be non-blank strings.")
    if len(set(items)) != len(items) or len(set(ranked)) != len(ranked):
        raise ValueError("Item IDs must be unique.")
    if not set(ranked) <= set(items) or set(node_weights) != set(items):
        raise ValueError("Ranking and node weights must match the input domain.")
    if any(
        isinstance(weight, bool) or not isinstance(weight, int | float) or not math.isfinite(weight)
        for weight in node_weights.values()
    ):
        raise ValueError("Node weights must be finite numbers.")
    ranked_set = set(ranked)
    remaining = sorted(
        (item for item in items if item not in ranked_set),
        key=lambda item: (-node_weights[item], item),
    )
    return ranked + tuple(remaining)


def expand_ranked_domain(
    input_item_ids: Sequence[str],
    retained_item_ids: Sequence[str],
    ranked_item_ids: Sequence[str],
    max_items: int,
) -> tuple[str, ...]:
    """Add the first eligible ranked item, without changing the input round.

    Ranking may contain only a subset of the input domain. An unchanged result
    means that the cap or the available ranking prevents further expansion.
    """
    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 0:
        raise ValueError("max_items must be a non-negative integer.")
    input_ids = tuple(input_item_ids)
    retained = tuple(retained_item_ids)
    ranked = tuple(ranked_item_ids)
    for name, values in (("input", input_ids), ("retained", retained), ("ranked", ranked)):
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError(f"{name} item IDs must be non-blank strings.")
        if len(set(values)) != len(values):
            raise ValueError(f"{name} item IDs must be unique.")
    input_set = set(input_ids)
    retained_set = set(retained)
    if not retained_set <= input_set or not set(ranked) <= input_set:
        raise ValueError("Retained and ranked items must belong to the input round.")
    if len(retained) > max_items:
        raise ValueError("The retained domain exceeds max_items.")
    if len(retained) == max_items:
        return retained
    for item in ranked:
        if item not in retained_set:
            return (*retained, item)
    return retained