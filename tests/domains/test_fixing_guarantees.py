"""Guarantees must never be inferred from heuristic MIS selection."""

import pytest

from qreduce.domains import FixingEntry


def test_safe_fixing_requires_a_proof() -> None:
    with pytest.raises(ValueError):
        FixingEntry("a", {"delta": 0}, "dominance", "certified_rule", "safe")
    entry = FixingEntry("a", {"delta": 0}, "dominance", "certified_rule", "safe", "proof-1")
    assert entry.to_dict()["proof_reference"] == "proof-1"


def test_mis_cannot_claim_safe_fixing() -> None:
    with pytest.raises(ValueError):
        FixingEntry("a", {"delta": 0}, "mis", "mis_heuristic", "safe", "proof")