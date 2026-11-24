"""Single-attempt batch creation and shared, read-only result handling."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter, sleep, time
from typing import Any, Protocol

from qreduce.solving.mwis.contracts import RawMISSample
from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    MAX_POLL_INTERVAL_SECONDS,
    PasqalCloudEmulatorService,
    _get_sdk_version,
)

TERMINAL_BATCH_STATUSES = frozenset({"DONE", "ERROR", "CANCELED", "TIMED_OUT"})
REJECTED_HTTP_STATUSES = frozenset({400, 401, 403, 404, 405, 413, 415, 422, 429})
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    batch_id: str
    service: PasqalCloudEmulatorService
    shots: int
    submission_timestamp: float
    atom_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PollResult:
    batch_id: str
    is_complete: bool
    is_success: bool
    status: str
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class BatchResults:
    batch_id: str
    counts: dict[str, int]
    atom_order: tuple[str, ...]
    total_shots: int


class SubmissionCallback(Protocol):
    def __call__(self, submission: SubmissionResult) -> None: ...


class SubmissionPersistenceError(RuntimeError):
    def __init__(self, batch_id: str):
        super().__init__("Could not persist the submitted batch reference.")
        self.batch_id = batch_id


class SubmissionOutcomeUnknown(RuntimeError):
    """A creation request failed without a definitive response or usable ID."""


class SubmissionRejected(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"Pasqal Cloud rejected batch creation (HTTP {status_code}).")
        self.status_code = status_code


def valid_batch_id(batch_id: object) -> bool:
    return isinstance(batch_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", batch_id) is not None


def submit_sequence(
    sequence,
    connection,
    service: PasqalCloudEmulatorService,
    shots: int,
    *,
    on_submitted: SubmissionCallback,
    deadline: float | None = None,
) -> SubmissionResult:
    """Use the pinned SDK's wire format without its creation retries or reads.

    SDK 0.24.0 exposes no create-only, no-retry public API returning the raw ID.
    Reuse its endpoint, authenticator and unmodified requests session, but not
    its retry wrapper or Batch parsing. Do not follow redirects on creation.
    """
    if service != PasqalCloudEmulatorService.EMU_FREE or _get_sdk_version() != "0.24.0":
        raise ValueError("Unsupported service or SDK version for single-attempt submission.")
    if not callable(on_submitted):
        raise ValueError("A reference writer is required before batch creation.")

    from pasqal_cloud.http_client import HTTPClient
    from pulser.backend import BitStrings, EmulationConfig

    transport = connection.cloud_client._client
    if type(transport) is not HTTPClient or transport.session.verify is not True:
        raise ValueError("Unexpected Pasqal transport or TLS settings.")
    if not sequence.is_measured():
        sequence = type(sequence).from_abstract_repr(sequence.to_abstract_repr())
        sequence.measure("ground-rydberg")
    atom_order = tuple(sequence.register.qubit_ids)
    config = EmulationConfig(default_num_shots=shots, observables=[BitStrings()])
    payload = {
        "sequence_builder": sequence.to_abstract_repr(),
        "webhook": None,
        "jobs": [{}],  # EMU_FREE takes shots from EmulationConfig, not QPU runs.
        "open": False,
        "device_type": "EMU_FREE",
        "backend_configuration": config.to_abstract_repr(),
        "project_id": transport.project_id,
    }
    batch_id = create_batch_once(transport, payload, deadline=deadline)
    result = SubmissionResult(batch_id, service, shots, time(), atom_order)
    try:
        on_submitted(result)
    except Exception:
        raise SubmissionPersistenceError(batch_id) from None
    return result


def create_batch_once(transport, payload: dict[str, Any], *, deadline: float | None = None) -> str:
    """Create a batch without redirects or SDK retries; return only a validated ID."""
    from pasqal_cloud.http_client import HTTPClient

    if (_get_sdk_version() != "0.24.0" or type(transport) is not HTTPClient
            or transport.session.verify is not True):
        raise ValueError("Unexpected Pasqal SDK, transport or TLS settings.")
    url = transport._get_url("send_batch")
    # Resolve authentication before the creation call; it cannot replay the POST.
    token = transport.user_token()
    if not token:
        raise ValueError("Pasqal authentication did not return a token.")

    def authorize(request):
        request.headers["Authorization"] = f"Bearer {token}"
        return request

    timeout = REQUEST_TIMEOUT_SECONDS
    if deadline is not None:
        timeout = min(timeout, deadline - perf_counter())
        if timeout <= 0:
            raise TimeoutError("Execution budget expired before batch creation.")
    try:
        response = transport.session.request(
            "POST", url, json=payload, allow_redirects=False, timeout=timeout,
            auth=authorize, headers={"User-Agent": transport.user_agent},
        )
        if response.status_code in REJECTED_HTTP_STATUSES:
            raise SubmissionRejected(response.status_code)
        if not 200 <= response.status_code < 300:
            raise ValueError("Unexpected creation response.")
        batch_id = response.json()["data"]["id"]
        if not valid_batch_id(batch_id):
            raise ValueError("Unexpected batch identifier.")
    except SubmissionRejected:
        raise
    except Exception:
        raise SubmissionOutcomeUnknown(
            "Batch creation outcome unknown. Reconcile with Pasqal before submitting again."
        ) from None

    return batch_id


def poll_batch_status(batch_id: str, connection) -> PollResult:
    from pasqal_cloud.errors import BatchFetchingError

    try:
        status = connection.cloud_client.get_batch_status(batch_id).name
    except (Exception, BatchFetchingError) as error:
        # The SDK wraps HTTPError using exception chaining. Never expose its
        # text, which can include authentication or response data.
        response = getattr(error.__cause__, "response", None)
        code = getattr(response, "status_code", None)
        status = "NOT_FOUND" if code == 404 else "ACCESS_ERROR"
        return PollResult(batch_id, False, False, status, "Cannot read Pasqal batch status.")
    return PollResult(batch_id, status in TERMINAL_BATCH_STATUSES, status == "DONE", status)


def wait_for_completion(
    batch_id: str,
    connection,
    timeout_seconds: float | None,
) -> PollResult:
    """None waits indefinitely, zero checks once. In-flight SDK reads may overrun."""
    deadline = None if timeout_seconds in (None, 0) else perf_counter() + timeout_seconds
    interval = DEFAULT_POLL_INTERVAL_SECONDS
    while True:
        if deadline is not None and perf_counter() >= deadline:
            return PollResult(batch_id, False, False, "LOCAL_TIMEOUT")
        poll = poll_batch_status(batch_id, connection)
        if deadline is not None and perf_counter() >= deadline:
            return PollResult(batch_id, False, False, "LOCAL_TIMEOUT")
        if poll.is_complete or poll.error_message or timeout_seconds == 0:
            return poll
        delay = interval if deadline is None else min(interval, max(0.0, deadline - perf_counter()))
        sleep(delay)
        interval = min(interval * 1.5, MAX_POLL_INTERVAL_SECONDS)


def read_batch_results(
    batch_id: str,
    connection,
    *,
    expected_project: str,
    expected_shots: int | None,
    job_ids: tuple[str, ...] | None = None,
    expected_device_type: str | None = None,
) -> BatchResults:
    """Read one completed SDK Job and its Pulser Results, not the batch wrapper.

    Args:
        batch_id: Pasqal batch identifier.
        connection: PasqalCloudConnection instance.
        expected_project: Project ID to validate against.
        expected_shots: Expected shot count, or None to skip validation.
        job_ids: Optional job IDs to validate against.
        expected_device_type: Expected device type (e.g., "EMU_FREE", "FRESNEL").
            If None, accepts EMU_FREE for backwards compatibility.
    """
    from pasqal_cloud.errors import BatchFetchingError
    from pulser import Sequence
    from pulser.backend.results import Results

    try:
        batch = connection.cloud_client.get_batch(batch_id)
    except BatchFetchingError:
        raise RuntimeError("Cannot read Pasqal batch data.") from None

    # Validate device type
    allowed_device_types = {expected_device_type} if expected_device_type else {"EMU_FREE"}
    # For QPU, accept any non-emulator device type
    is_qpu_target = expected_device_type and expected_device_type not in ("EMU_FREE", "EMU_SV", "EMU_MPS")
    if is_qpu_target:
        # QPU: device type must match exactly or be the target
        if batch.device_type not in (expected_device_type,):
            raise ValueError(f"Unexpected device type: {batch.device_type}, expected {expected_device_type}.")
    elif batch.device_type not in allowed_device_types:
        raise ValueError(f"Unexpected device type: {batch.device_type}.")

    if (batch.id != batch_id or batch.project_id != expected_project
            or batch.status != "DONE" or batch.open):
        raise ValueError("Unexpected Pasqal batch identity or state.")
    jobs = batch.ordered_jobs
    if len(jobs) != 1 or (job_ids is not None and (jobs[0].id,) != job_ids):
        raise ValueError("Expected exactly one matching Pasqal job.")
    job = jobs[0]
    if job.status != "DONE" or job.batch_id != batch_id or job.project_id != expected_project:
        raise ValueError("Unexpected Pasqal job identity or state.")
    result = job.full_result
    if not result:
        raise ValueError("Completed Pasqal job has no results.")
    if result.get("serialised_results") is not None:
        sample = Results.from_abstract_repr(result["serialised_results"])
    else:
        sequence = Sequence.from_abstract_repr(batch.sequence_builder)
        if not result.get("counter") or job.variables:
            raise ValueError("No usable counts for the submitted fixed sequence.")
        sample = Results.from_final_bitstrings(
            atom_order=sequence.register.qubit_ids,
            total_duration=sequence.get_duration(),
            final_bitstrings=result["counter"],
        )
    counts = dict(sample.final_bitstrings)
    atoms = tuple(sample.atom_order)
    total = _validate_counts(counts, atoms)
    if expected_shots is not None and total != expected_shots:
        raise ValueError("Received shot count does not match the submission.")
    return BatchResults(batch_id, counts, atoms, total)


def _validate_counts(counts: Mapping[str, int], atoms: tuple[str, ...]) -> int:
    if not atoms or any(not isinstance(atom, str) or not atom for atom in atoms):
        raise ValueError("Invalid atom identifiers in Pasqal results.")
    if len(set(atoms)) != len(atoms) or not counts or any(
        not isinstance(bits, str) or len(bits) != len(atoms) or set(bits) - {"0", "1"}
        or type(count) is not int or count <= 0 for bits, count in counts.items()
    ):
        raise ValueError("Invalid atom order or bitstring counts in Pasqal results.")
    return sum(counts.values())


def decode_results_to_samples(
    batch_results: BatchResults,
    node_order: tuple[str, ...],
    compiled_job_id: str,
    service: PasqalCloudEmulatorService | str,
    compilation_params: dict[str, Any],
    weight_encoding_mode: str,
    *,
    atom_to_node_map: Mapping[str, str],
    source_backend_id: str = "pasqal_cloud_emulator",
) -> list[RawMISSample]:
    """Translate provider bit positions into the original canonical node order.

    Args:
        batch_results: Results from read_batch_results.
        node_order: Canonical node order from the compiled job.
        compiled_job_id: Identifier for the compiled job.
        service: Emulator service or "qpu" for QPU jobs.
        compilation_params: Compilation parameters to include in samples.
        weight_encoding_mode: Weight encoding mode string.
        atom_to_node_map: Mapping from atom IDs (q0, q1, ...) to node IDs.
        source_backend_id: Backend identifier for samples (default: pasqal_cloud_emulator).
    """
    atoms = batch_results.atom_order
    if (_validate_counts(batch_results.counts, atoms) != batch_results.total_shots
            or set(atoms) != set(atom_to_node_map) or len(atoms) != len(node_order)
            or len(set(node_order)) != len(node_order)
            or set(node_order) != set(atom_to_node_map.values())):
        raise ValueError("Pasqal results do not match the original node mapping.")
    by_node = {atom_to_node_map[atom]: pos for pos, atom in enumerate(atoms)}
    positions = tuple(by_node[node] for node in node_order)
    canonical_counts = sorted(
        (tuple(int(bits[pos]) for pos in positions), count)
        for bits, count in batch_results.counts.items()
    )

    # Determine service value for execution parameters
    if isinstance(service, str):
        service_value = service
    else:
        service_value = service.value

    return [
        RawMISSample(
            raw_sample_id=f"{compiled_job_id}:sample:{i:04d}",
            node_order=node_order,
            delta=delta,
            occurrence_count=count,
            source_provider_id="pasqal",
            source_backend_id=source_backend_id,
            effective_compilation_parameters=compilation_params,
            effective_execution_parameters={
                "shots": batch_results.total_shots,
                "batch_id": batch_results.batch_id,
                "emulator_service": service_value,
                "weight_encoding_mode": weight_encoding_mode,
            },
        )
        for i, (delta, count) in enumerate(canonical_counts)
    ]