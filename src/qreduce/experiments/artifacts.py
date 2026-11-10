"""Filesystem artifact contracts for repository-internal QReduce experiments."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from qreduce.artifacts.metadata import sha256_hex

ARTIFACT_SCHEMA_VERSION = "1.0"
_REQUIRED_ARTIFACT_FILES = (
    "config_used.json",
    "problem.json",
    "run_result.json",
    "run_manifest.json",
)


class ExperimentArtifactError(RuntimeError):
    """Raised when an experiment artifact directory is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class ExperimentRunArtifacts:
    """Loaded, JSON-native data for one completed repository experiment run."""

    run_directory: Path
    manifest: Mapping[str, object]
    config: Mapping[str, object]
    problem: object
    result: Mapping[str, object]
    canonical_mwis_problem: Mapping[str, object] | None


def load_experiment_run(run_directory: str | Path) -> ExperimentRunArtifacts:
    """Load one fully published experiment run without invoking the QReduce pipeline."""

    directory = Path(run_directory)
    if not directory.is_dir():
        raise ExperimentArtifactError(
            f"Experiment run directory does not exist: {directory}"
        )
    missing_files = [
        name for name in _REQUIRED_ARTIFACT_FILES if not (directory / name).is_file()
    ]
    if missing_files:
        raise ExperimentArtifactError(
            f"Experiment run is incomplete; missing: {', '.join(missing_files)}"
        )

    manifest = _read_json_object(directory / "run_manifest.json")
    _require_string(manifest, "artifact_schema_version")
    _require_string(manifest, "experiment_id")
    _require_string(manifest, "run_id")
    _require_string(manifest, "created_at")
    if manifest["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise ExperimentArtifactError(
            f"Unsupported artifact schema version {manifest['artifact_schema_version']!r}; "
            f"expected {ARTIFACT_SCHEMA_VERSION!r}."
        )

    canonical_path = directory / "canonical_mwis_problem.json"
    config = _read_json_object(directory / "config_used.json")
    problem = _read_json(directory / "problem.json")
    result = _read_json_object(directory / "run_result.json")
    canonical_mwis_problem = (
        _read_json_object(canonical_path) if canonical_path.is_file() else None
    )
    _validate_content_hashes(
        manifest,
        {
            "config_used.json": config,
            "problem.json": problem,
            "run_result.json": result,
            **(
                {"canonical_mwis_problem.json": canonical_mwis_problem}
                if canonical_mwis_problem is not None
                else {}
            ),
        },
    )
    return ExperimentRunArtifacts(
        run_directory=directory,
        manifest=manifest,
        config=config,
        problem=problem,
        result=result,
        canonical_mwis_problem=canonical_mwis_problem,
    )


def _read_json(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as artifact_file:
            return json.load(artifact_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentArtifactError(
            f"Cannot load JSON artifact {path}: {error}"
        ) from error


def _read_json_object(path: Path) -> Mapping[str, object]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ExperimentArtifactError(f"Artifact {path} must contain a JSON object.")
    return value


def _require_string(values: Mapping[str, object], field: str) -> None:
    if not isinstance(values.get(field), str) or not values[field].strip():
        raise ExperimentArtifactError(f"Artifact manifest has no non-blank {field!r}.")


def _validate_content_hashes(
    manifest: Mapping[str, object], files: Mapping[str, object]
) -> None:
    expected_hashes = manifest.get("files")
    if not isinstance(expected_hashes, dict):
        raise ExperimentArtifactError(
            "Artifact manifest must contain a file-hash object."
        )
    if set(expected_hashes) != set(files):
        raise ExperimentArtifactError(
            "Artifact manifest file hashes do not match the published files."
        )
    for filename, contents in files.items():
        expected_hash = expected_hashes[filename]
        if not isinstance(expected_hash, str) or expected_hash != sha256_hex(contents):
            raise ExperimentArtifactError(
                f"Content hash mismatch for artifact {filename}."
            )
