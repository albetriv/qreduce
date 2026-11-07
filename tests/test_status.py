"""Tests for normalized pipeline status contracts."""

from qreduce.status import (
    AdoptionStatus,
    PipelineStage,
    RunStatus,
    TerminalReason,
)


def test_normalized_status_values_are_json_strings() -> None:
    """Statuses retain their distinct normalized values when serialized."""

    assert RunStatus.SUCCESS.value == "success"
    assert PipelineStage.MIS.value == "mis"
    assert TerminalReason.INVALID_CONFIGURATION.value == "invalid_configuration"
    assert AdoptionStatus.NOT_ADOPTED.value == "not_adopted"


def test_terminal_reason_and_adoption_status_are_separate_concepts() -> None:
    """A reason never doubles as an adoption decision."""

    assert TerminalReason.POSTCHECK_FAILED.value != AdoptionStatus.NOT_ADOPTED.value