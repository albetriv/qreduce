"""Tests for the monotonic multi-round fixing invariant."""

from dataclasses import replace

import pytest

from qreduce.domains import FixingEntry, FixingManifest
from qreduce.pipeline.rounds import (
    cumulative_fixing_manifest,
    validate_manifest_sequence,
    validate_round_manifest,
)


def manifest(retained, excluded, index):
    return FixingManifest(
        retained_item_ids=retained,
        excluded_item_ids=excluded,
        entries=tuple(FixingEntry(item, {f"delta_{item}": 0.0}, "excluded") for item in excluded),
        origin="heuristic_candidate_domain",
        round_index=index,
    )


def test_monotonic_manifests_return_final_domain():
    first = manifest(("a", "b"), ("c",), 0)
    second = manifest(("b",), ("a",), 1)
    assert validate_manifest_sequence(("a", "b", "c"), (first, second)) == ("b",)


def test_previously_excluded_item_cannot_reappear():
    first = manifest(("a", "b"), ("c",), 0)
    second = manifest(("b", "c"), ("a",), 1)
    with pytest.raises(ValueError, match="partition"):
        validate_manifest_sequence(("a", "b", "c"), (first, second))


def test_round_index_and_input_partition_are_validated():
    first = manifest(("a",), ("b",), 0)
    with pytest.raises(ValueError, match="round index"):
        validate_round_manifest(("a", "b"), replace(first, round_index=1), 0)
    with pytest.raises(ValueError, match="partition"):
        validate_round_manifest(("a", "b", "c"), first, 0)


def test_cumulative_manifest_retains_original_entries_and_domain():
    first = manifest(("a", "b"), ("c",), 0)
    second = manifest(("b",), ("a",), 1)
    cumulative = cumulative_fixing_manifest(("a", "b", "c"), (first, second))
    assert cumulative.retained_item_ids == ("b",)
    assert cumulative.excluded_item_ids == ("a", "c")
    assert cumulative.entries == first.entries + second.entries
    assert cumulative.round_index == 1


def test_cumulative_manifest_rejects_conflicting_variable_assignments():
    first = manifest(("a", "b"), ("c",), 0)
    second = manifest(("b",), ("a",), 1)
    second = replace(second, entries=(FixingEntry("a", {"delta_c": 1.0}, "excluded"),))
    with pytest.raises(ValueError, match="Conflicting cumulative fixing"):
        cumulative_fixing_manifest(("a", "b", "c"), (first, second))


def test_cumulative_manifest_requires_a_round():
    with pytest.raises(ValueError, match="At least one"):
        cumulative_fixing_manifest(("a",), ())