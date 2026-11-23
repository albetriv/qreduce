"""Persistence and recovery for Pasqal Cloud remote jobs.

This module provides durable persistence of batch_id and job context before
polling begins, enabling recovery of results in a new session without
resubmitting jobs.

The job reference is saved to a JSON file immediately after submission,
before any polling starts. This ensures that the batch_id is preserved
even if the local process crashes or times out during polling.

Recovery uses only the batch_id and project credentials - no resubmission.
The original job context (node order, etc.) is required to decode results
back to canonical node IDs.

INTEGRATION WITH SUBMISSION ADAPTER:
This module provides the SubmissionCallback implementation that the
submission adapter uses for pre-polling persistence. The flow is:
1. submit_sequence() calls on_submitted callback
2. Callback creates PasqalCloudJobReference from SubmissionResult
3. Callback writes atomic file via save_job_reference()
4. Only after successful write does polling begin
"""

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from qreduce.artifacts.metadata import pretty_json
from qreduce.solving.mwis.contracts import RawMISSample
from qreduce.solving.mwis.pasqal_credentials import resolve_pasqal_credentials

logger = logging.getLogger(__name__)

# Schema version for job reference files
JOB_REFERENCE_SCHEMA_VERSION = "1.1"  # Updated for unified schema


@dataclass(frozen=True, slots=True)
class PasqalCloudJobReference:
    """Persistent reference to a submitted Pasqal Cloud job.

    Contains all information needed to:
    1. Query job status from Pasqal Cloud
    2. Decode results back to canonical node IDs
    3. Audit the job submission context

    Does NOT contain credentials - those are resolved at recovery time.

    Schema version 1.1 adds:
    - atom_to_node_map: mapping from SDK atom names (q0, q1...) to node IDs
    - project_id: non-secret identifier for audit (NOT credentials)
    """

    # Pasqal Cloud identifiers
    batch_id: str
    emulator_service: str
    project_id: str  # Non-secret, for audit only

    # QReduce job context
    compiled_job_id: str
    run_id: str
    round_index: int
    node_order: tuple[str, ...]
    shots: int

    # Atom-to-node mapping for result decoding
    atom_to_node_map: dict[str, str]  # e.g., {"q0": "AAPL", "q1": "GOOG"}

    # Submission metadata
    submission_timestamp: str  # ISO format
    pasqal_profile: str
    sdk_version: str

    # Optional - may not be available immediately
    job_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {
            "schema_version": JOB_REFERENCE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "emulator_service": self.emulator_service,
            "project_id": self.project_id,
            "compiled_job_id": self.compiled_job_id,
            "run_id": self.run_id,
            "round_index": self.round_index,
            "node_order": list(self.node_order),
            "shots": self.shots,
            "atom_to_node_map": self.atom_to_node_map,
            "submission_timestamp": self.submission_timestamp,
            "pasqal_profile": self.pasqal_profile,
            "sdk_version": self.sdk_version,
            "job_ids": list(self.job_ids) if self.job_ids else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PasqalCloudJobReference":
        """Create a job reference from a dictionary."""
        schema = data.get("schema_version")
        if schema not in {"1.0", "1.1", JOB_REFERENCE_SCHEMA_VERSION}:
            raise ValueError(f"Unsupported job reference schema: {schema}")

        # Handle backwards compatibility with schema 1.0
        atom_to_node_map = data.get("atom_to_node_map")
        if atom_to_node_map is None:
            # Schema 1.0 didn't have this, reconstruct from node_order
            node_order = data["node_order"]
            atom_to_node_map = {f"q{i}": node for i, node in enumerate(node_order)}

        project_id = data.get("project_id", "unknown")

        return cls(
            batch_id=data["batch_id"],
            emulator_service=data["emulator_service"],
            project_id=project_id,
            compiled_job_id=data["compiled_job_id"],
            run_id=data["run_id"],
            round_index=data["round_index"],
            node_order=tuple(data["node_order"]),
            shots=data["shots"],
            atom_to_node_map=dict(atom_to_node_map),
            submission_timestamp=data["submission_timestamp"],
            pasqal_profile=data["pasqal_profile"],
            sdk_version=data["sdk_version"],
            job_ids=tuple(data["job_ids"]) if data.get("job_ids") else None,
        )


class PasqalCloudJobPersistenceError(RuntimeError):
    """Raised when job reference persistence fails."""


class PasqalCloudJobRecoveryError(RuntimeError):
    """Raised when job recovery fails."""


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_job_reference_directory(directory: Path) -> None:
    """Verify the journal can be written and synced before submitting."""
    if not directory.exists():
        prepare_job_reference_directory(directory.parent)
        directory.mkdir(exist_ok=True)
        _sync_directory(directory.parent)
    with NamedTemporaryFile(dir=directory) as probe:
        probe.write(b"qreduce")
        probe.flush()
        os.fsync(probe.fileno())
    _sync_directory(directory)


def create_job_reference_from_submission(
    submission,  # SubmissionResult from pasqal_cloud_submission
    *,
    compiled_job_id: str,
    run_id: str,
    round_index: int,
    node_order: tuple[str, ...],
    project_id: str,
    pasqal_profile: str,
    sdk_version: str,
) -> PasqalCloudJobReference:
    """Create a PasqalCloudJobReference from a SubmissionResult.

    This bridges the submission adapter output to the persistence schema.
    """
    # Build atom-to-node mapping
    atom_to_node_map = {
        atom: node
        for atom, node in zip(submission.atom_order, node_order, strict=True)
    }

    return PasqalCloudJobReference(
        batch_id=submission.batch_id,
        emulator_service=submission.service.value,
        project_id=project_id,
        compiled_job_id=compiled_job_id,
        run_id=run_id,
        round_index=round_index,
        node_order=node_order,
        shots=submission.shots,
        atom_to_node_map=atom_to_node_map,
        submission_timestamp=datetime.fromtimestamp(
            submission.submission_timestamp, tz=UTC
        ).isoformat(),
        pasqal_profile=pasqal_profile,
        sdk_version=sdk_version,
    )


def make_persistence_callback(
    output_directory: Path,
    *,
    compiled_job_id: str,
    run_id: str,
    round_index: int,
    node_order: tuple[str, ...],
    project_id: str,
    pasqal_profile: str,
    sdk_version: str,
):
    """Create a SubmissionCallback that persists job references atomically.

    Returns a callable suitable for passing to submit_sequence(on_submitted=...).

    The callback will:
    1. Create a PasqalCloudJobReference from the submission
    2. Write it atomically to output_directory
    3. Raise PasqalCloudJobPersistenceError if write fails

    If the callback raises, the submission adapter will wrap the error
    with the batch_id included for manual recovery.
    """
    def callback(submission) -> None:
        reference = create_job_reference_from_submission(
            submission,
            compiled_job_id=compiled_job_id,
            run_id=run_id,
            round_index=round_index,
            node_order=node_order,
            project_id=project_id,
            pasqal_profile=pasqal_profile,
            sdk_version=sdk_version,
        )
        save_job_reference(reference, output_directory)

    return callback


def save_job_reference(
    reference: PasqalCloudJobReference,
    output_directory: Path,
    *,
    filename: str | None = None,
) -> Path:
    """Persist a job reference to a durable file before polling.

    This should be called immediately after receiving the batch_id from
    Pasqal Cloud, before starting to poll for results.

    Args:
        reference: The job reference to persist.
        output_directory: Directory to save the reference file.
        filename: Optional custom filename. Default: pasqal_cloud_job_{batch_id}.json

    Returns:
        Path to the saved file.

    Raises:
        PasqalCloudJobPersistenceError: If the file cannot be written.
    """
    if filename is None:
        # Sanitize batch_id for use in filename
        safe_batch_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in reference.batch_id)
        filename = f"pasqal_cloud_job_{safe_batch_id}.json"

    output_path = output_directory / filename

    temporary_path = None
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_directory, delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(pretty_json(reference.to_dict()) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output_path)
        _sync_directory(output_directory)
        logger.debug("Saved job reference to %s", output_path)
        return output_path
    except (OSError, TypeError):
        raise PasqalCloudJobPersistenceError("Failed to save Pasqal job reference.") from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_job_reference(path: Path) -> PasqalCloudJobReference:
    """Load a job reference from a file.

    Args:
        path: Path to the job reference file.

    Returns:
        The loaded job reference.

    Raises:
        PasqalCloudJobPersistenceError: If the file cannot be read or parsed.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PasqalCloudJobReference.from_dict(data)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        raise PasqalCloudJobPersistenceError("Cannot load Pasqal job reference.") from None


@dataclass(frozen=True, slots=True)
class JobRecoveryResult:
    """Result of recovering a Pasqal Cloud job."""

    batch_id: str
    status: str
    is_terminal: bool
    is_success: bool
    results: Mapping[str, int] | None  # bitstring -> count
    node_order: tuple[str, ...]
    shots_requested: int | None
    shots_received: int | None
    error_message: str | None = None
    atom_order: tuple[str, ...] = ()


def recover_job_results(
    reference: PasqalCloudJobReference,
    *,
    profile: str | None = None,
    timeout_seconds: float = 0,
) -> JobRecoveryResult:
    """Recover a submitted batch using its original project and shot count."""
    from qreduce.solving.mwis.pasqal_cloud_submission import valid_batch_id

    if (not valid_batch_id(reference.batch_id) or reference.emulator_service != "emu_free"
            or not reference.project_id or reference.project_id == "unknown"
            or type(reference.shots) is not int or reference.shots <= 0):
        raise PasqalCloudJobRecoveryError("Invalid or incomplete Pasqal job reference.")
    return _recover_batch(
        reference.batch_id, profile=profile or reference.pasqal_profile,
        timeout_seconds=timeout_seconds, project_id=reference.project_id,
        shots=reference.shots, node_order=reference.node_order, job_ids=reference.job_ids,
    )


def recover_batch_counts(
    batch_id: str, *, project_id: str, profile: str = "default", timeout_seconds: float = 0,
) -> JobRecoveryResult:
    """Recover raw provider counts when the original node mapping is unavailable."""
    from qreduce.solving.mwis.pasqal_cloud_submission import valid_batch_id

    if not valid_batch_id(batch_id) or not project_id:
        raise PasqalCloudJobRecoveryError("A valid batch ID and original project ID are required.")
    return _recover_batch(batch_id, profile=profile, timeout_seconds=timeout_seconds, project_id=project_id)


def _recover_batch(
    batch_id: str, *, profile: str, timeout_seconds: float, project_id: str,
    shots: int | None = None, node_order: tuple[str, ...] = (), job_ids: tuple[str, ...] | None = None,
) -> JobRecoveryResult:
    from time import perf_counter

    from qreduce.config import validate_timeout_value
    from qreduce.solving.mwis.pasqal_cloud_submission import read_batch_results, wait_for_completion

    error = validate_timeout_value(timeout_seconds, "timeout_seconds")
    if error:
        raise PasqalCloudJobRecoveryError(error)
    deadline = perf_counter() + timeout_seconds if timeout_seconds else None
    if os.getenv("PASQAL_SKIP_SSL_VERIFY"):
        raise PasqalCloudJobRecoveryError("QReduce refuses to connect with TLS verification disabled.")
    try:
        from pasqal_cloud import PasqalCloudConnection
    except ImportError:
        raise PasqalCloudJobRecoveryError("Install the Pasqal SDK with: poetry install --with experiments") from None

    phase = "credentials"
    try:
        credentials = resolve_pasqal_credentials(profile=profile)
        if credentials.project_id != project_id:
            raise PasqalCloudJobRecoveryError("Configured Pasqal project does not match the original project.")
        phase = "connect"
        connection = PasqalCloudConnection(
            username=credentials.username, password=credentials.password, project_id=credentials.project_id,
        )
        phase = "poll"
        remaining = 0 if deadline is None else deadline - perf_counter()
        if deadline is not None and remaining <= 0:
            return JobRecoveryResult(batch_id, "local_timeout", False, False, None, node_order, shots, None)
        poll = wait_for_completion(batch_id, connection, remaining)
        if not poll.is_success:
            return JobRecoveryResult(
                batch_id, poll.status.lower(), poll.is_complete or poll.status == "NOT_FOUND",
                False, None, node_order, shots, None, poll.error_message,
            )
        phase = "read_results"
        batch = read_batch_results(batch_id, connection, expected_project=project_id,
                                   expected_shots=shots, job_ids=job_ids)
        if deadline is not None and perf_counter() >= deadline:
            return JobRecoveryResult(batch_id, "local_timeout", False, False, None, node_order, shots, None)
        return JobRecoveryResult(batch_id, "completed", True, True, batch.counts, node_order,
                                 shots, batch.total_shots, atom_order=batch.atom_order)
    except PasqalCloudJobRecoveryError:
        raise
    except Exception:
        raise PasqalCloudJobRecoveryError(
            f"Pasqal recovery failed during {phase}. Batch ID: {batch_id}."
        ) from None


def recover_job_to_samples(
    reference: PasqalCloudJobReference,
    *,
    compiled_job_id: str,
    compilation_params: dict[str, Any],
    weight_encoding_mode: str,
    profile: str | None = None,
    timeout_seconds: float = 0,
) -> tuple[list[RawMISSample], JobRecoveryResult]:
    """Recover results and decode to RawMISSample list.

    Combines recover_job_results with decode_results_to_samples for
    full recovery to pipeline-compatible format.

    Returns:
        Tuple of (samples, recovery_result). Samples is empty if not successful.
    """
    from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
        PasqalCloudEmulatorService,
    )
    from qreduce.solving.mwis.pasqal_cloud_submission import (
        BatchResults,
        decode_results_to_samples,
    )

    if compiled_job_id != reference.compiled_job_id:
        raise PasqalCloudJobRecoveryError("Compiled job ID does not match the Pasqal reference.")

    recovery = recover_job_results(reference, profile=profile, timeout_seconds=timeout_seconds)

    if not recovery.is_success or recovery.results is None:
        return [], recovery

    # Reconstruct BatchResults for decoding
    batch_results = BatchResults(
        batch_id=recovery.batch_id,
        counts=dict(recovery.results),
        atom_order=recovery.atom_order,
        total_shots=recovery.shots_received or 0,
    )

    service = PasqalCloudEmulatorService(reference.emulator_service)

    try:
        samples = decode_results_to_samples(
            batch_results=batch_results,
            node_order=reference.node_order,
            compiled_job_id=compiled_job_id,
            service=service,
            compilation_params=compilation_params,
            weight_encoding_mode=weight_encoding_mode,
            atom_to_node_map=reference.atom_to_node_map,
        )
    except (ValueError, TypeError):
        raise PasqalCloudJobRecoveryError(
            f"Pasqal samples do not match the original node mapping. Batch ID: {reference.batch_id}."
        ) from None

    return samples, recovery


def find_job_references(
    directory: Path,
    *,
    run_id: str | None = None,
    batch_id: str | None = None,
) -> list[tuple[Path, PasqalCloudJobReference]]:
    """Find job reference files in a directory.

    Args:
        directory: Directory to search.
        run_id: Optional filter by run_id.
        batch_id: Optional filter by batch_id.

    Returns:
        List of (path, reference) tuples, sorted by submission timestamp.
    """
    if not directory.is_dir():
        return []

    results: list[tuple[Path, PasqalCloudJobReference]] = []
    for path in directory.glob("pasqal_cloud_job_*.json"):
        try:
            ref = load_job_reference(path)
            if run_id is not None and ref.run_id != run_id:
                continue
            if batch_id is not None and ref.batch_id != batch_id:
                continue
            results.append((path, ref))
        except PasqalCloudJobPersistenceError:
            # Skip invalid files
            continue

    # Sort by submission timestamp
    results.sort(key=lambda x: x[1].submission_timestamp)
    return results
