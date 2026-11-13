"""Filesystem artifact contracts for repository-internal QReduce experiments."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from qreduce.artifacts.metadata import sha256_hex

ARTIFACT_SCHEMA_VERSION = "1.1"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
_REQUIRED_ARTIFACT_FILES = (
    "config_used.json",
    "experiment_metadata.json",
    "problem.json",
    "run_result.json",
    "run_manifest.json",
)
_ROUND_RESULT_PATTERN = re.compile(r"^round_(\d+)_result\.json$")


class ExperimentArtifactError(RuntimeError):
    """Raised when an experiment artifact directory is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class ExperimentRunArtifacts:
    """Loaded, JSON-native data for one completed repository experiment run."""

    run_directory: Path
    manifest: Mapping[str, object]
    config: Mapping[str, object]
    experiment_metadata: Mapping[str, object]
    problem: object
    result: Mapping[str, object]
    canonical_mwis_problem: Mapping[str, object] | None
    round_results: tuple[Mapping[str, object], ...] = ()
    recovery_attempts: tuple[Mapping[str, object], ...] = ()

    @property
    def schema_version(self) -> str:
        """Return the artifact schema version."""
        return str(self.manifest.get("artifact_schema_version", "1.0"))

    @property
    def reduction_round_count(self) -> int:
        """Return the number of reduction rounds (0 for classical-only baseline)."""
        # Schema 1.1 has round_count directly
        if "round_count" in self.manifest:
            return int(self.manifest["round_count"])  # type: ignore[arg-type]
        # Schema 1.0 compatibility: count round result files
        return len(self.round_results)

    @property
    def has_reduction(self) -> bool:
        """True if at least one reduction round was executed."""
        return self.reduction_round_count > 0

    @property
    def is_classical_only(self) -> bool:
        """True if this was a classical-only baseline with no MWIS reduction."""
        return self.reduction_round_count == 0

    @property
    def is_multi_round(self) -> bool:
        """True if this artifact was produced by a multi-round run.

        For backward compatibility with schema 1.0. In schema 1.1+, use
        has_reduction or reduction_round_count instead.
        """
        # Schema 1.0 compatibility
        if "run_mode" in self.manifest:
            return self.manifest.get("run_mode") == "multi_round"
        # Schema 1.1: multi-round means more than one round
        return self.reduction_round_count > 1

    @property
    def fixing_manifest(self) -> Mapping[str, object] | None:
        """Return the cumulative fixing manifest, if available.

        Present in schema 1.1+ for both classical-only and reduction runs.
        For classical-only, origin is 'no_reduction' with all items retained.
        """
        manifest_data = self.manifest.get("fixing_manifest")
        if manifest_data is not None and isinstance(manifest_data, dict):
            return manifest_data
        return None


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
    schema_version = manifest["artifact_schema_version"]
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise ExperimentArtifactError(
            f"Unsupported artifact schema version {schema_version!r}; "
            f"supported versions: {', '.join(sorted(_SUPPORTED_SCHEMA_VERSIONS))}."
        )

    canonical_path = directory / "canonical_mwis_problem.json"
    config = _read_json_object(directory / "config_used.json")
    experiment_metadata = _read_json_object(directory / "experiment_metadata.json")
    problem = _read_json(directory / "problem.json")
    result = _read_json_object(directory / "run_result.json")
    canonical_mwis_problem = (
        _read_json_object(canonical_path) if canonical_path.is_file() else None
    )

    # Load multi-round artifacts if present
    round_results, round_files = _load_round_results(directory, manifest)
    recovery_attempts, recovery_file = _load_recovery_attempts(directory, manifest)

    # Build extra hashes for model export
    model_export = manifest.get("model_export")
    extra_hashes: dict[str, str] = {}
    if isinstance(model_export, dict) and model_export.get("external") is False:
        path = model_export.get("path")
        if not isinstance(path, str) or Path(path).suffix.lower() not in {".lp", ".mps"}:
            raise ExperimentArtifactError("Invalid model export path in manifest.")
        filename = Path(path).name
        try:
            extra_hashes[filename] = sha256((directory / filename).read_bytes()).hexdigest()
        except OSError as error:
            raise ExperimentArtifactError(f"Cannot load model export {filename}.") from error
        if extra_hashes[filename] != model_export.get("sha256"):
            raise ExperimentArtifactError(f"Content hash mismatch for artifact {filename}.")

    # Build files dict for hash validation
    files_for_hash: dict[str, object] = {
        "config_used.json": config,
        "experiment_metadata.json": experiment_metadata,
        "problem.json": problem,
        "run_result.json": result,
    }
    if canonical_mwis_problem is not None:
        files_for_hash["canonical_mwis_problem.json"] = canonical_mwis_problem

    # Add round results to hash validation
    files_for_hash.update(round_files)

    # Add recovery attempts to hash validation
    if recovery_file:
        files_for_hash.update(recovery_file)

    _validate_content_hashes(manifest, files_for_hash, extra_hashes)

    return ExperimentRunArtifacts(
        run_directory=directory,
        manifest=manifest,
        config=config,
        experiment_metadata=experiment_metadata,
        problem=problem,
        result=result,
        canonical_mwis_problem=canonical_mwis_problem,
        round_results=round_results,
        recovery_attempts=recovery_attempts,
    )


def _load_round_results(
    directory: Path, manifest: Mapping[str, object]
) -> tuple[tuple[Mapping[str, object], ...], dict[str, object]]:
    """Load round_XX_result.json files if present in manifest."""
    expected_hashes = manifest.get("files", {})
    if not isinstance(expected_hashes, dict):
        return (), {}

    round_files: list[tuple[int, str, Mapping[str, object]]] = []
    files_for_hash: dict[str, object] = {}

    for filename in expected_hashes:
        match = _ROUND_RESULT_PATTERN.match(filename)
        if match:
            round_index = int(match.group(1))
            filepath = directory / filename
            if not filepath.is_file():
                raise ExperimentArtifactError(
                    f"Round result file listed in manifest but missing: {filename}"
                )
            content = _read_json_object(filepath)
            round_files.append((round_index, filename, content))
            files_for_hash[filename] = content

    # Sort by round index
    round_files.sort(key=lambda x: x[0])
    return tuple(r[2] for r in round_files), files_for_hash


def _load_recovery_attempts(
    directory: Path, manifest: Mapping[str, object]
) -> tuple[tuple[Mapping[str, object], ...], dict[str, object]]:
    """Load recovery_attempts.json if present in manifest."""
    expected_hashes = manifest.get("files", {})
    if not isinstance(expected_hashes, dict):
        return (), {}

    filename = "recovery_attempts.json"
    if filename not in expected_hashes:
        return (), {}

    filepath = directory / filename
    if not filepath.is_file():
        raise ExperimentArtifactError(
            f"Recovery attempts file listed in manifest but missing: {filename}"
        )

    content = _read_json(filepath)
    if not isinstance(content, list):
        raise ExperimentArtifactError(
            f"Recovery attempts file must contain a JSON array: {filename}"
        )

    return tuple(content), {filename: content}  # type: ignore[misc]


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
    manifest: Mapping[str, object], files: Mapping[str, object],
    extra_hashes: Mapping[str, str],
) -> None:
    expected_hashes = manifest.get("files")
    if not isinstance(expected_hashes, dict):
        raise ExperimentArtifactError(
            "Artifact manifest must contain a file-hash object."
        )
    if set(expected_hashes) != set(files) | set(extra_hashes):
        raise ExperimentArtifactError(
            "Artifact manifest file hashes do not match the published files."
        )
    for filename, contents in files.items():
        expected_hash = expected_hashes[filename]
        if not isinstance(expected_hash, str) or expected_hash != sha256_hex(contents):
            raise ExperimentArtifactError(
                f"Content hash mismatch for artifact {filename}."
            )
    for filename, digest in extra_hashes.items():
        if expected_hashes[filename] != digest:
            raise ExperimentArtifactError(f"Content hash mismatch for artifact {filename}.")
