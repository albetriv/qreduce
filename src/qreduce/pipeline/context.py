"""Shared validation and provenance helpers for pipeline execution."""

from qreduce.artifacts.metadata import redact_metadata, sha256_hex, to_primitive
from qreduce.domains import LogicalVariableCounts, ReducibleProblemAdapter


def compute_input_hash(adapter: ReducibleProblemAdapter, problem: object) -> str | None:
    """Hash the optional redacted input description; unavailable input has no hash."""
    describe = getattr(adapter, "describe_input", None)
    if callable(describe):
        try:
            return sha256_hex(redact_metadata(to_primitive(describe(problem))))
        except Exception:  # noqa: BLE001, S110 - Input identity is optional.
            pass
    return None


def validate_logical_counts(value: object) -> LogicalVariableCounts:
    """Require the adapter's logical-variable-count contract."""
    if not isinstance(value, LogicalVariableCounts):
        raise TypeError("describe_logical_variables must return LogicalVariableCounts.")
    return value