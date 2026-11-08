"""Tests for deterministic artifact metadata serialization and redaction."""

import json

from qreduce.artifacts.metadata import (
    canonical_json,
    redact_metadata,
    sha256_hex,
    utc_created_at,
)
from qreduce.models import (
    ArtifactOptions,
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
)
from qreduce.status import (
    PostcheckMode,
)


def make_config() -> ResolvedRunConfig:
    """Build a resolved configuration containing nested contracts and enums."""

    return ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(1, 1, 5, 2, 0.1, 3, 60.0),
        lambda_edge=2.0,
        lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0),
        allow_noncertifying_penalty=False,
        mis_solver_id="local_greedy",
        mis_execution=MISExecutionOptions(2, 17, 4, True, 3, 0.25, 20),
        classical_solve=ClassicalSolveOptions(
            "cplex", 30.0, 0.01, 1, False, 1e-6, 1e-6, 1e-7, 1e-7, PostcheckMode.STRICT
        ),
        artifacts=ArtifactOptions("run-001", "1.0", "0.1.0", "caller_supplied", True),
    )


def test_canonical_json_and_hash_ignore_mapping_insertion_order() -> None:
    """Equivalent mapping data produces the same persisted bytes and digest."""

    left = {"b": 2, "a": {"z": 1, "x": 3}}
    right = {"a": {"x": 3, "z": 1}, "b": 2}

    assert canonical_json(left) == canonical_json(right)
    assert sha256_hex(left) == sha256_hex(right)


def test_config_serializes_nested_dataclasses_and_enums() -> None:
    """Resolved configuration has no SDK objects or non-primitive enum values."""

    serialized_config = make_config().to_dict()

    assert json.loads(canonical_json(serialized_config))["mis_solver_id"] == "local_greedy"


def test_redaction_removes_secrets_recursively_and_from_url_queries() -> None:
    """Metadata serialization cannot expose common credentials or tokens."""

    redacted = redact_metadata(
        {
            "token": "top-secret",
            "nested": {"api_key": "other-secret"},
            "endpoint": "https://provider.example/jobs?access_token=secret&id=42",
        }
    )

    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "secret" not in redacted["endpoint"]
    assert "id=42" in redacted["endpoint"]


def test_created_at_is_explicit_utc_iso_timestamp() -> None:
    """Artifact timestamps identify UTC rather than depending on local timezone."""

    assert utc_created_at().endswith("Z")