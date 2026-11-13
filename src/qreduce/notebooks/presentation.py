"""Reusable vertical-table presentation helpers for QReduce notebooks.

Pandas is imported lazily so these helpers do not add a runtime dependency to
the QReduce core package.
"""

import json
from collections.abc import Mapping, Sequence


def display_vertical(values: Mapping[str, object], *, title: str | None = None) -> None:
    """Display one mapping as a vertical field/value table."""

    if title is not None:
        print(title)
    _display_dataframe(
        [
            {"campo": field, "valore": _format_value(value)}
            for field, value in values.items()
        ]
    )


def display_records(
    records: Sequence[Mapping[str, object]] | None,
    *,
    record_label: str,
) -> None:
    """Display repeated records vertically instead of as a wide table."""

    if not record_label.strip():
        raise ValueError("record_label cannot be blank.")
    rows: list[dict[str, object]] = []
    for index, record in enumerate(records or ()):
        record_id = record.get("raw_sample_id", f"{record_label}-{index + 1}")
        rows.extend(
            {
                record_label: record_id,
                "campo": field,
                "valore": _format_value(value),
            }
            for field, value in record.items()
        )
    _display_dataframe(rows, columns=[record_label, "campo", "valore"])


def _format_value(value: object) -> object:
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(value, list | tuple):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return value


def _display_dataframe(rows: list[dict[str, object]], columns: list[str] | None = None) -> None:
    import pandas as pd
    from IPython.display import display

    display(pd.DataFrame(rows, columns=columns))