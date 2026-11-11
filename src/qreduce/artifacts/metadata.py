"""Deterministic serialization, hashing and sensitive-metadata redaction."""

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_REDACTED_VALUE = "[REDACTED]"


def to_primitive(value: object) -> object:
    """Recursively convert supported contracts into JSON-compatible primitives."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            dataclass_field.name: to_primitive(getattr(value, dataclass_field.name))
            for dataclass_field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): to_primitive(nested_value)
            for key, nested_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, frozenset):
        return sorted((to_primitive(item) for item in value), key=canonical_json)
    if isinstance(value, tuple | list):
        return [to_primitive(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Value of type {type(value).__name__} is not JSON serializable.")


def canonical_json(value: object) -> str:
    """Serialize a contract deterministically as compact UTF-8-safe JSON text."""

    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def pretty_json(value: object) -> str:
    """Serialize a contract as deterministic, human-readable UTF-8-safe JSON text."""

    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return canonical JSON encoded as UTF-8 bytes."""

    return canonical_json(value).encode("utf-8")


def sha256_hex(value: object) -> str:
    """Return the SHA-256 digest of canonical JSON for ``value``."""

    return sha256(canonical_json_bytes(value)).hexdigest()


def redact_metadata(value: object) -> object:
    """Redact common secret-bearing keys and sensitive URL query parameters."""

    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, nested_value in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                result[text_key] = _REDACTED_VALUE
            else:
                result[text_key] = redact_metadata(nested_value)
        return result
    if isinstance(value, tuple | list | frozenset):
        return [redact_metadata(item) for item in value]
    if isinstance(value, str) and _looks_like_url(value):
        return _redact_url_query(value)
    return value


def utc_created_at() -> str:
    """Return an ISO 8601 UTC timestamp with explicit ``Z`` offset."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _is_sensitive_key(key: str) -> bool:
    normalized_key = key.lower().replace("-", "_")
    return any(part in normalized_key for part in _SENSITIVE_KEY_PARTS)


def _looks_like_url(value: str) -> bool:
    parsed_value = urlsplit(value)
    return bool(parsed_value.scheme and parsed_value.netloc and parsed_value.query)


def _redact_url_query(value: str) -> str:
    parsed_value = urlsplit(value)
    redacted_query = urlencode(
        [
            (key, _REDACTED_VALUE if _is_sensitive_key(key) else nested_value)
            for key, nested_value in parse_qsl(parsed_value.query, keep_blank_values=True)
        ]
    )
    return urlunsplit(
        (
            parsed_value.scheme,
            parsed_value.netloc,
            parsed_value.path,
            redacted_query,
            parsed_value.fragment,
        )
    )