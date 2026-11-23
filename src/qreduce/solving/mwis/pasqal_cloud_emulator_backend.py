"""Pasqal Cloud emulator backend for remote MIS execution.

This backend implements neutral-atom MIS solving via Pasqal Cloud emulators:
1. Exact presolve for trivially solvable graphs (edgeless) - no cloud submission
2. Remote execution on EMU_FREE via the pinned Pasqal Cloud SDK transport
3. Transparent weight encoding mode (classical ranking, not physical encoding)
4. Persistent batch_id before polling for recovery support

The backend requires explicit selection of the free EMU_FREE service.

Credentials are resolved from:
1. Environment variables: PASQAL_USERNAME, PASQAL_PASSWORD, PASQAL_PROJECT_ID
2. Profile file: ~/.pasqual/credentials

Weights are used only for classical ranking of samples, not physically
encoded in the Hamiltonian.
"""

from collections.abc import Mapping
from contextlib import ExitStack
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

from qreduce.capabilities import RuntimeCapabilities
from qreduce.cloud_tls import CloudTLSConfigurationError
from qreduce.solving.mwis.audit import WeightEncodingMode
from qreduce.solving.mwis.compilation import validate_compilation_request
from qreduce.solving.mwis.contracts import (
    CompiledMISJob,
    MISBackendResult,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.solving.mwis.pasqal_cloud_tls import pasqal_ca_environment
from qreduce.solving.mwis.pasqal_credentials import (
    PasqalCredentialsError,
    resolve_pasqal_credentials,
)
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout, search_layout
from qreduce.solving.mwis.presolve import PresolveStatus, try_presolve
from qreduce.solving.mwis.pulse_strategy import (
    build_pulse_sequence,
    default_smoothed_annealing_config,
    diagnose_pulse_strategy,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


class PasqalCloudEmulatorService(StrEnum):
    """Supported Pasqal Cloud emulator services."""

    EMU_FREE = "emu_free"


# Default polling interval and limits
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
MAX_POLL_INTERVAL_SECONDS = 30.0
EMU_FREE_DEVICE_ID = "cloud:emu_free"
# Conservative remote ceiling from the Pasqal emulator catalog (detailed entry).
EMU_FREE_MAX_ATOMS = 12

# Payload version: increment when changing payload structure
PAYLOAD_VERSION = 1


def _sdk_available() -> tuple[bool, str | None]:
    """Check if Pulser SDK is available for compilation.

    Note: This checks only Pulser availability for compilation.
    The pasqal-cloud SDK is required only for solve() with cloud execution.
    Presolve jobs don't require pasqal-cloud.
    """
    try:
        from pulser import Register  # noqa: F401
        from pulser.devices import AnalogDevice  # noqa: F401

        return True, None
    except ImportError:
        return False, "Pulser SDK is unavailable. Install with: poetry install --with experiments"


def _cloud_sdk_available() -> tuple[bool, str | None]:
    """Check if pasqal-cloud SDK is available for remote execution."""
    try:
        from pasqal_cloud import PasqalCloudConnection  # noqa: F401
        from pasqal_cloud.backends import RemoteEmuFreeBackend  # noqa: F401

        return True, None
    except ImportError:
        return False, "pasqal-cloud SDK is unavailable or incompatible. Install with: poetry install --with experiments"


def _get_sdk_version() -> str:
    """Get the installed pasqal-cloud version."""
    try:
        return version("pasqal-cloud")
    except PackageNotFoundError:
        return "unknown"


def _sanitize_sdk_error(_error: Exception) -> str:
    """Never expose uncontrolled provider exception messages."""
    return "Pasqal SDK operation failed (details redacted)."


class PasqalCloudEmulatorMISBackend:
    """Neutral-atom MIS backend using Pasqal Cloud emulators.

    This backend:
    1. Compiles MIS graphs to Pulser sequences locally
    2. Submits sequences to Pasqal Cloud emulators
    3. Persists batch_id before polling for recovery support
    4. Returns raw samples for classical ranking by MWIS weight

    Weight handling:
    - Weights are NOT physically encoded in the Hamiltonian
    - The backend solves unweighted MIS (all nodes have equal "weight")
    - Weights are used only for classical ranking of samples post-execution
    - This is explicitly declared as WeightEncodingMode.CLASSICAL_RANKING

    Required compilation parameters:
    - _emulator_service: Explicit emulator service (currently only "emu_free")

    Optional compilation parameters:
    - pasqal_profile: Profile name for credentials (default: "default")
    - layout_attempts: Number of layout search attempts (default: 1000)
    - layout_seed: Seed for layout search (default: 0)
    """

    provider_id = "pasqal"
    backend_id = "pasqal_cloud_emulator"

    def __init__(self, *, job_reference_directory: Path | None = None) -> None:
        """Set the directory used to persist remote job references."""
        self._job_reference_directory = job_reference_directory

    def capabilities(self) -> RuntimeCapabilities:
        """Probe the optional SDK and declare only supported execution controls."""
        available, diagnostic = _sdk_available()
        return RuntimeCapabilities(
            provider_id=self.provider_id,
            backend_id=self.backend_id,
            backend_family=BackendFamily.NEUTRAL_ATOM,
            execution_mode=ExecutionMode.REMOTE,
            runtime_available=available,
            supported_problem_forms=frozenset({ProblemForm.MIS_GRAPH}),
            supports_random_seed=False,
            supports_solution_count=True,
            supports_execution_time_limit=True,
            supports_compilation_time_limit=False,
            supports_async_execution=False,  # Pipeline uses synchronous solve()
            supports_cancellation=False,
            supports_local_simulator=False,
            supports_remote_qpu=False,
            requires_geometric_mapping=True,
            requires_device_mapping=False,
            required_credentials=True,
            supported_parameter_names=frozenset({"shots"}),
            supported_compilation_parameter_names=frozenset({
                "layout_attempts",
                "layout_seed",
                "pasqal_profile",
            }),
            required_sdk="pasqal-cloud",
            supported_device_ids=frozenset({EMU_FREE_DEVICE_ID}),
            maximum_variables=None,  # The remote limit does not apply to local presolve.
            runtime_terminal_reason=None if available else TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
            diagnostic_message=diagnostic,
        )

    def compile(self, problem, request):
        """Compile graph to Pulser sequence ready for cloud submission.

        Compilation flow:
        1. Validate emulator service
        2. Check for exact presolve (edgeless graphs)
        3. If presolve applies, return special payload with presolve result
        4. Otherwise, build Pulser sequence for cloud submission

        The compiled job contains the sequence and all context needed
        to submit and decode results, but no actual submission occurs.
        """
        start = perf_counter()
        caps = self.capabilities()
        validation = validate_compilation_request(problem, request, caps)

        def fail(reason: TerminalReason, message: str) -> MISCompilationResult:
            return MISCompilationResult(
                None,
                request.requested_provider_id,
                request.requested_backend_id,
                None,
                None,
                perf_counter() - start,
                MISCompletionStatus.FAILED,
                terminal_reason=reason,
                diagnostic_message=message,
            )

        if not validation.is_valid:
            return fail(
                validation.terminal_reason or TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "; ".join(i.message for i in validation.issues),
            )

        # Validate internal parameters
        params = dict(request.compilation_parameters)
        emulator_service = params.pop("_emulator_service", None)
        params.pop("_cost_consent", None)  # Legacy config; EMU_FREE needs no credits.

        if emulator_service is None:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Missing _emulator_service: explicit emulator selection required.",
            )

        try:
            service = PasqalCloudEmulatorService(emulator_service)
        except ValueError:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"Unsupported emulator service: {emulator_service}. Supported: {', '.join(s.value for s in PasqalCloudEmulatorService)}.",
            )

        if service != PasqalCloudEmulatorService.EMU_FREE:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"Only {PasqalCloudEmulatorService.EMU_FREE.value} is supported in this version.",
            )

        profile = params.get("pasqal_profile", "default")

        # Validate layout parameters
        attempts = params.get("layout_attempts", 1000)
        seed = params.get("layout_seed", 0)

        if isinstance(seed, bool) or not isinstance(seed, int):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_seed must be an integer.",
            )

        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_attempts must be a positive integer.",
            )

        # Check for exact presolve opportunity (edgeless graphs)
        presolve_result = try_presolve(problem.graph, requested_backend_id=self.backend_id)

        if presolve_result.status == PresolveStatus.APPLIED:
            # Edgeless graph: return presolve result without cloud submission
            elapsed = perf_counter() - start
            payload = {
                "presolve_applied": True,
                "presolve_reason": presolve_result.reason.value if presolve_result.reason else None,
                "presolve_delta": list(presolve_result.delta) if presolve_result.delta else None,
                "presolve_weight": presolve_result.selection_weight,
                "presolve_size": presolve_result.num_selected,
                "is_certified_optimal": presolve_result.is_certified_optimal,
                "node_order": list(request.node_order),
                "target": "cloud_presolve",
                "emulator_service": service.value,
                "sdk_version": "presolve",
                "weight_encoding_mode": WeightEncodingMode.NOT_APPLICABLE.value,
            }
            job = CompiledMISJob(
                compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-cloud-presolve",
                run_id=request.run_id,
                round_index=request.round_index,
                node_order=request.node_order,
                problem_form=ProblemForm.MIS_GRAPH,
                compiled_problem=problem,
                requested_provider_id=request.requested_provider_id,
                requested_backend_id=request.requested_backend_id,
                effective_provider_id="qreduce",
                effective_backend_id="presolve_exact",
                backend_family=BackendFamily.CLASSICAL_EXACT,
                execution_mode=ExecutionMode.LOCAL,
                effective_device_id=None,
                runtime_seconds=elapsed,
                effective_compilation_parameters=params,
                capabilities_snapshot=caps,
                provider_payload_type="pasqal.cloud.presolve",
                provider_payload_version=PAYLOAD_VERSION,
                provider_payload=payload,
            )
            return MISCompilationResult(
                job,
                request.requested_provider_id,
                request.requested_backend_id,
                "qreduce",
                "presolve_exact",
                elapsed,
                MISCompletionStatus.COMPLETED,
                effective_compilation_parameters=params,
            )

        if len(problem.graph.node_ids) > EMU_FREE_MAX_ATOMS:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"QReduce limits remote EMU_FREE runs to {EMU_FREE_MAX_ATOMS} atoms.",
            )

        # Non-trivial graph: build Pulser sequence for cloud submission
        try:
            from pulser import Register
            from pulser.devices import AnalogDevice

            if not problem.graph.node_ids:
                raise ValueError("empty graph is unsupported")

            def make_register(coords):
                return Register({
                    f"q{i}": coords[node]
                    for i, node in enumerate(problem.graph.node_ids)
                })

            def accept(coords):
                try:
                    AnalogDevice.validate_register(make_register(coords))
                    return True
                except ValueError:
                    return False

            coords, diag = search_layout(
                problem.graph,
                10.0,
                1.0,
                attempts=attempts,
                seed=seed,
                min_distance=AnalogDevice.min_atom_distance,
                accept=accept,
            )
            register = make_register(coords)
            AnalogDevice.validate_register(register)
            if not diagnose_layout(problem.graph, coords, 10.0, 1.0)["valid"]:
                raise ValueError("invalid final layout")

            # Use smoothed annealing pulse strategy
            pulse_config = default_smoothed_annealing_config()

            # Set a conservative edge penalty scale
            from math import dist
            if problem.graph.edges:
                min_edge = min(
                    AnalogDevice.interaction_coeff / dist(coords[a], coords[b]) ** 6
                    for a, b in problem.graph.edges
                )
                from dataclasses import replace
                pulse_config = replace(
                    pulse_config,
                    final_detuning_rad_per_us=min(pulse_config.final_detuning_rad_per_us, 0.5 * min_edge)
                )
            seq = build_pulse_sequence(pulse_config, register, AnalogDevice)

            # Compute minimum distance for diagnostics
            min_dist = None
            if len(coords) >= 2:
                import math
                distances = []
                nodes_list = list(coords.keys())
                for i in range(len(nodes_list)):
                    for j in range(i + 1, len(nodes_list)):
                        xi, yi = coords[nodes_list[i]]
                        xj, yj = coords[nodes_list[j]]
                        d = math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2)
                        distances.append(d)
                min_dist = min(distances) if distances else None

            # Get pulse diagnostics
            pulse_diagnostics = diagnose_pulse_strategy(pulse_config, min_distance_um=min_dist)

            payload = {
                "presolve_applied": False,
                "sequence_abstract_repr": seq.to_abstract_repr(),
                "target": "AnalogDevice",
                "emulator_service": service.value,
                "node_order": list(request.node_order),
                "coordinates": [list(coords[n]) for n in request.node_order],
                "mapping": diag,
                "sdk_version": _get_sdk_version(),
                "pulser_version": version("pulser-core"),
                "weight_encoding_mode": WeightEncodingMode.CLASSICAL_RANKING.value,
                "pulse_strategy": pulse_config.to_dict(),
                "pulse_diagnostics": pulse_diagnostics.to_dict(),
                "min_interatomic_distance_um": min_dist,
                "pasqal_profile": profile,
            }

        except (ValueError, TypeError) as error:
            return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, str(error))
        except Exception as error:  # noqa: BLE001 - normalize provider failures
            return fail(
                TerminalReason.MIS_COMPILATION_FAILED,
                _sanitize_sdk_error(error),
            )

        elapsed = perf_counter() - start
        job = CompiledMISJob(
            compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-cloud-emu",
            run_id=request.run_id,
            round_index=request.round_index,
            node_order=request.node_order,
            problem_form=ProblemForm.MIS_GRAPH,
            compiled_problem=problem,
            requested_provider_id=request.requested_provider_id,
            requested_backend_id=request.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.NEUTRAL_ATOM,
            execution_mode=ExecutionMode.REMOTE,
            effective_device_id=EMU_FREE_DEVICE_ID,
            runtime_seconds=elapsed,
            effective_compilation_parameters=params,
            capabilities_snapshot=caps,
            provider_payload_type="pasqal.cloud.sequence",
            provider_payload_version=PAYLOAD_VERSION,
            provider_payload=payload,
        )
        return MISCompilationResult(
            job,
            request.requested_provider_id,
            request.requested_backend_id,
            self.provider_id,
            self.backend_id,
            elapsed,
            MISCompletionStatus.COMPLETED,
            effective_compilation_parameters=params,
        )

    def solve(self, compiled_job: CompiledMISJob, request) -> MISBackendResult:
        """Execute compiled job: return presolve result or submit to cloud.

        For presolve jobs, returns the deterministic result immediately.
        For cloud jobs:
        1. Establish connection with credentials
        2. Submit sequence to emulator
        3. Persist batch_id before polling (for recovery)
        4. Poll for results with timeout
        5. Decode and return raw samples

        The batch_id is persisted through the job_reference callback before
        any polling begins, allowing recovery in case of local failures.
        """
        start = perf_counter()
        caps = self.capabilities()
        shots = request.execution_parameters.get("shots", request.requested_solution_count)

        def result(
            samples: list[RawMISSample],
            reason: TerminalReason | None = None,
            message: str | None = None,
            effective_params: dict[str, Any] | None = None,
        ) -> MISBackendResult:
            return MISBackendResult(
                samples=tuple(samples),
                requested_provider_id=compiled_job.requested_provider_id,
                requested_backend_id=compiled_job.requested_backend_id,
                effective_provider_id=compiled_job.effective_provider_id,
                effective_backend_id=compiled_job.effective_backend_id,
                backend_family=compiled_job.backend_family,
                execution_mode=compiled_job.execution_mode,
                capabilities_snapshot=caps,
                runtime_seconds=perf_counter() - start,
                effective_execution_parameters=effective_params or request.execution_parameters,
                completion_status=MISCompletionStatus.FAILED if reason else MISCompletionStatus.COMPLETED,
                terminal_reason=reason,
                diagnostic_message=message,
                effective_device_id=compiled_job.effective_device_id,
            )

        # =====================================================================
        # Common validations
        # =====================================================================

        # Validate job identity
        if (
            request.compiled_job_id != compiled_job.compiled_job_id
            or request.run_id != compiled_job.run_id
            or request.round_index != compiled_job.round_index
            or request.node_order != compiled_job.node_order
        ):
            return result([], TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH, "Job identity mismatch.")

        # Validate execution parameters
        if (
            set(request.execution_parameters) - {"shots"}
            or isinstance(shots, bool)
            or not isinstance(shots, int)
            or shots < 1
        ):
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Invalid execution parameters: shots must be a positive integer.",
            )

        # random_seed not supported
        if request.random_seed is not None:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Sampling random_seed not supported by this backend.",
            )

        payload = compiled_job.provider_payload

        # =====================================================================
        # Handle presolve case
        # =====================================================================
        if compiled_job.provider_payload_type == "pasqal.cloud.presolve":
            expected = try_presolve(compiled_job.compiled_problem.graph, requested_backend_id=self.backend_id)
            if (
                compiled_job.provider_payload_version != PAYLOAD_VERSION
                or expected.status != PresolveStatus.APPLIED
                or not isinstance(payload, Mapping)
                or payload.get("presolve_applied") is not True
                or payload.get("node_order") != list(compiled_job.node_order)
                or payload.get("presolve_delta") != list(expected.delta or ())
                or payload.get("presolve_weight") != expected.selection_weight
                or payload.get("presolve_size") != expected.num_selected
                or payload.get("is_certified_optimal") is not True
            ):
                return result([], TerminalReason.MIS_EXECUTION_FAILED, "Invalid presolve payload.")

            presolve_delta = payload.get("presolve_delta")
            if presolve_delta is None:
                return result([], TerminalReason.MIS_EXECUTION_FAILED, "Missing presolve delta.")

            sample = RawMISSample(
                raw_sample_id=f"{compiled_job.compiled_job_id}:presolve:exact",
                node_order=compiled_job.node_order,
                delta=tuple(presolve_delta),
                occurrence_count=1,
                source_provider_id="qreduce",
                source_backend_id="presolve_exact",
                effective_compilation_parameters=compiled_job.effective_compilation_parameters,
                effective_execution_parameters={
                    "requested_shots": shots,
                    "effective_shots": 0,
                    "deterministic_result_count": 1,
                    "presolve_reason": payload.get("presolve_reason"),
                    "is_certified_optimal": True,
                    "weight_encoding_mode": WeightEncodingMode.NOT_APPLICABLE.value,
                },
                raw_backend_metadata={
                    "presolve_weight": payload.get("presolve_weight"),
                    "presolve_size": payload.get("presolve_size"),
                },
            )
            return result(
                [sample],
                effective_params={
                    "requested_shots": shots,
                    "effective_shots": 0,
                    "deterministic_result_count": 1,
                },
            )

        # =====================================================================
        # Cloud execution path
        # =====================================================================

        # Check pasqal-cloud SDK availability (separate from Pulser)
        cloud_available, cloud_diagnostic = _cloud_sdk_available()
        if not cloud_available:
            return result(
                [],
                TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                cloud_diagnostic,
            )

        # Validate payload
        if (
            compiled_job.provider_payload_type != "pasqal.cloud.sequence"
            or compiled_job.provider_payload_version != PAYLOAD_VERSION
            or not isinstance(payload, Mapping)
            or payload.get("target") != "AnalogDevice"
            or payload.get("node_order") != list(compiled_job.node_order)
            or payload.get("presolve_applied") is not False
            or compiled_job.effective_device_id != EMU_FREE_DEVICE_ID
            or len(compiled_job.node_order) > EMU_FREE_MAX_ATOMS
        ):
            return result([], TerminalReason.MIS_EXECUTION_FAILED, "Invalid cloud payload.")

        emulator_service = payload.get("emulator_service")
        if emulator_service != PasqalCloudEmulatorService.EMU_FREE.value:
            return result(
                [],
                TerminalReason.MIS_EXECUTION_FAILED,
                "Unsupported emulator service in payload.",
            )

        if self._job_reference_directory is None:
            return result([], TerminalReason.MIS_EXECUTION_FAILED, "A durable Pasqal job reference directory is required.")

        profile = payload.get("pasqal_profile", "default")
        batch_id: str | None = None  # Will be set after submission
        budget = request.residual_time_budget_seconds
        deadline = start + budget if budget > 0 else None
        phase = "prepare"

        tls = ExitStack()
        try:
            from pasqal_cloud import PasqalCloudConnection
            from pulser import Sequence
            from pulser.devices import AnalogDevice

            from qreduce.solving.mwis.pasqal_cloud_persistence import (
                make_persistence_callback,
                prepare_job_reference_directory,
            )
            from qreduce.solving.mwis.pasqal_cloud_submission import (
                SubmissionOutcomeUnknown,
                SubmissionPersistenceError,
                SubmissionRejected,
                decode_results_to_samples,
                read_batch_results,
                submit_sequence,
                wait_for_completion,
            )

            # Reconstruct sequence from payload
            seq = Sequence.from_abstract_repr(payload["sequence_abstract_repr"])
            if tuple(seq.register.qubit_ids) != tuple(f"q{i}" for i in range(len(compiled_job.node_order))):
                raise ValueError("invalid atom order in sequence")

            # Validate register against device
            if seq.device != AnalogDevice:
                raise ValueError("invalid device in sequence")
            AnalogDevice.validate_register(seq.register)

            # Validate geometry
            coords = {
                node: tuple(float(value) for value in seq.register.qubits[f"q{i}"])
                for i, node in enumerate(compiled_job.node_order)
            }
            if not diagnose_layout(compiled_job.compiled_problem.graph, coords, 10.0, 1.0)["valid"]:
                raise ValueError("invalid geometry in sequence")

            # Security: Refuse to connect if TLS verification is disabled
            # The SDK respects PASQAL_SKIP_SSL_VERIFY which is a security risk
            import os
            if os.getenv("PASQAL_SKIP_SSL_VERIFY"):
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "PASQAL_SKIP_SSL_VERIFY is set. QReduce refuses to connect with TLS verification disabled.",
                )

            prepare_job_reference_directory(self._job_reference_directory)
            credentials = resolve_pasqal_credentials(profile=profile)
            tls.enter_context(pasqal_ca_environment())
            phase = "connect"
            connection = PasqalCloudConnection(
                username=credentials.username,
                password=credentials.password,
                project_id=credentials.project_id,
            )
            persistence_callback = make_persistence_callback(
                output_directory=self._job_reference_directory,
                compiled_job_id=compiled_job.compiled_job_id,
                run_id=request.run_id,
                round_index=request.round_index,
                node_order=compiled_job.node_order,
                project_id=credentials.project_id,
                pasqal_profile=profile,
                sdk_version=_get_sdk_version(),
            )
            phase = "submit"
            submission = submit_sequence(
                sequence=seq,
                connection=connection,
                service=PasqalCloudEmulatorService.EMU_FREE,
                shots=shots,
                on_submitted=persistence_callback,
                deadline=deadline,
            )
            batch_id = submission.batch_id

            phase = "poll"
            remaining = None if deadline is None else deadline - perf_counter()
            if remaining is not None and remaining <= 0:
                raise TimeoutError
            poll_result = wait_for_completion(batch_id, connection, remaining)
            if poll_result.status == "LOCAL_TIMEOUT":
                raise TimeoutError

            if not poll_result.is_success:
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    f"Batch failed with status {poll_result.status}. Batch ID: {batch_id}",
                    effective_params={"shots": shots, "batch_id": batch_id, "status": poll_result.status},
                )

            # Read results from completed batch
            phase = "read_results"
            batch_results = read_batch_results(
                batch_id, connection, expected_project=credentials.project_id, expected_shots=shots,
            )
            if deadline is not None and perf_counter() >= deadline:
                raise TimeoutError

            # Decode to samples using shared logic
            weight_encoding = payload.get("weight_encoding_mode", WeightEncodingMode.CLASSICAL_RANKING.value)

            phase = "decode"
            samples = decode_results_to_samples(
                batch_results=batch_results,
                node_order=compiled_job.node_order,
                compiled_job_id=compiled_job.compiled_job_id,
                service=PasqalCloudEmulatorService.EMU_FREE,
                compilation_params=compiled_job.effective_compilation_parameters,
                weight_encoding_mode=weight_encoding,
                atom_to_node_map=dict(zip(submission.atom_order, compiled_job.node_order, strict=True)),
            )

            return result(
                samples,
                effective_params={
                    "shots": shots,
                    "effective_shots": batch_results.total_shots,
                    "batch_id": batch_id,
                    "emulator_service": emulator_service,
                },
            )

        except SubmissionPersistenceError as e:
            # Persistence failed but batch was submitted - include batch_id for recovery
            return result(
                [],
                TerminalReason.MIS_EXECUTION_FAILED,
                f"Pre-polling persistence failed. Batch submitted with ID: {e.batch_id}. Manual recovery possible.",
                effective_params={"shots": shots, "batch_id": e.batch_id, "persistence_failed": True},
            )
        except SubmissionOutcomeUnknown as error:
            return result([], TerminalReason.MIS_EXECUTION_FAILED, str(error),
                          effective_params={"shots": shots, "status": "submission_outcome_unknown"})
        except SubmissionRejected as error:
            return result([], TerminalReason.MIS_EXECUTION_FAILED, str(error),
                          effective_params={"shots": shots, "status": "submission_rejected", "http_status": error.status_code})
        except TimeoutError:
            return result(
                [], TerminalReason.MIS_EXECUTION_TIME_BUDGET_EXHAUSTED,
                (f"Local deadline expired. Batch ID: {batch_id}; no cancellation was requested."
                 if batch_id else "Local deadline expired before batch creation."),
                effective_params={"shots": shots, "batch_id": batch_id, "timeout": True},
            )
        except PasqalCredentialsError:
            return result(
                [],
                TerminalReason.MIS_CREDENTIALS_UNAVAILABLE,
                "Pasqal credentials unavailable; check the environment or configured profile.",
            )
        except CloudTLSConfigurationError as error:
            return result([], TerminalReason.MIS_EXECUTION_FAILED, str(error))
        except Exception:  # noqa: BLE001 - normalize provider failures
            msg = f"Pasqal Cloud failed during {phase} (details redacted)."
            if batch_id:
                msg = f"{msg} Batch ID: {batch_id}"
            return result(
                [],
                TerminalReason.MIS_EXECUTION_FAILED,
                msg,
                effective_params={"shots": shots, "batch_id": batch_id, "phase": phase},
            )
        finally:
            tls.close()
