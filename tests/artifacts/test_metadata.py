"""Tests for deterministic artifact metadata serialization and redaction."""

import json

from qreduce.artifacts.metadata import (
    canonical_json,
    pretty_json,
    redact_metadata,
    sha256_hex,
    utc_created_at,
)
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
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
        run_identity=RunIdentity("run-001"),
    )


def test_canonical_json_and_hash_ignore_mapping_insertion_order() -> None:
    """Equivalent mapping data produces the same persisted bytes and digest."""

    left = {"b": 2, "a": {"z": 1, "x": 3}}
    right = {"a": {"x": 3, "z": 1}, "b": 2}

    assert canonical_json(left) == canonical_json(right)
    assert sha256_hex(left) == sha256_hex(right)


def test_pretty_json_is_deterministic_and_human_readable() -> None:
    """Readable artifact text preserves deterministic ordering without changing data."""

    serialized = pretty_json({"z": [1, {"b": True}], "a": {"x": 3}})

    assert serialized.startswith("{\n")
    assert '\n  "a": {' in serialized
    assert json.loads(serialized) == {"a": {"x": 3}, "z": [1, {"b": True}]}


def test_config_serializes_nested_dataclasses_and_enums() -> None:
    """Resolved configuration has no SDK objects or non-primitive enum values."""

    serialized_config = make_config().to_dict()

    assert (
        json.loads(canonical_json(serialized_config))["mis_solver_id"] == "local_greedy"
    )


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


def test_required_credentials_boolean_is_preserved_but_non_boolean_values_are_redacted() -> None:
    """Capability flags remain observable without making the key a secret bypass."""

    redacted = redact_metadata(
        {
            "required_credentials": True,
            "nested": {"required_credentials": "secret-value"},
        }
    )

    assert redacted["required_credentials"] is True
    assert redacted["nested"]["required_credentials"] == "[REDACTED]"


def test_created_at_is_explicit_utc_iso_timestamp() -> None:
    """Artifact timestamps identify UTC rather than depending on local timezone."""

    assert utc_created_at().endswith("Z")
