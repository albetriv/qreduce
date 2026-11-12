"""Validation of free logical-variable counts independent of solver models."""

import pytest

from qreduce.domains import LogicalVariableCounts


@pytest.mark.parametrize("value", [-1, True, 1.5, None, "1"])
def test_invalid_logical_counts_are_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="binary_free"):
        LogicalVariableCounts(value, 0, 0)


def test_zero_counts_are_known_and_serializable() -> None:
    assert LogicalVariableCounts(0, 0, 0).to_dict() == {
        "binary_free": 0, "integer_free": 0, "continuous_free": 0
    }