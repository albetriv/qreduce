"""Contract validation for domain evaluation metrics."""

import pytest

from qreduce.domains import DomainEvaluationMetric


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1"])
def test_metric_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        DomainEvaluationMetric("quality", value, "unitless", "higher", "test")


@pytest.mark.parametrize("field", ["metric_id", "unit", "comparison_convention", "provenance"])
def test_metric_rejects_blank_metadata(field) -> None:
    values = {"metric_id": "quality", "value": None, "unit": "unitless",
              "comparison_convention": "higher", "provenance": "test"}
    values[field] = " "
    with pytest.raises(ValueError):
        DomainEvaluationMetric(**values)