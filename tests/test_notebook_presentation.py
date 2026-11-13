"""Tests for shared vertical-table notebook presentation helpers."""

import pytest

from qreduce.notebooks import presentation


def test_display_vertical_formats_nested_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested JSON-native values remain legible in one field/value row."""

    pytest.importorskip("pandas")

    displayed = []
    monkeypatch.setattr(presentation, "_display_dataframe", lambda rows, columns=None: displayed.append((rows, columns)))

    presentation.display_vertical(
        {
            "solver": "scip",
            "parameters": {"threads": 1},
            "selected": ("asset-a", "asset-c"),
        },
        title="Configurazione",
    )

    assert displayed == [
        (
            [
        {"campo": "solver", "valore": "scip"},
        {"campo": "parameters", "valore": '{\n  "threads": 1\n}'},
        {"campo": "selected", "valore": '[\n  "asset-a",\n  "asset-c"\n]'},
            ],
            None,
        )
    ]


def test_display_records_uses_sample_identifier_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated artifact records use a vertical record/field/value layout."""

    pytest.importorskip("pandas")

    displayed = []
    monkeypatch.setattr(presentation, "_display_dataframe", lambda rows, columns=None: displayed.append((rows, columns)))

    presentation.display_records(
        [
            {"raw_sample_id": "sample-001", "energy": -2.2},
            {"energy": -1.4},
        ],
        record_label="sample",
    )

    assert displayed == [
        (
            [
        {"sample": "sample-001", "campo": "raw_sample_id", "valore": "sample-001"},
        {"sample": "sample-001", "campo": "energy", "valore": -2.2},
        {"sample": "sample-2", "campo": "energy", "valore": -1.4},
            ],
            ["sample", "campo", "valore"],
        )
    ]


def test_display_records_preserves_columns_for_empty_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty record set still renders the expected vertical table columns."""

    pytest.importorskip("pandas")

    displayed = []
    monkeypatch.setattr(presentation, "_display_dataframe", lambda rows, columns=None: displayed.append((rows, columns)))

    presentation.display_records([], record_label="sample")

    assert displayed == [([], ["sample", "campo", "valore"])]


def test_display_records_rejects_blank_record_label() -> None:
    """The record identifier column must have a meaningful name."""

    with pytest.raises(ValueError, match="record_label"):
        presentation.display_records([], record_label=" ")