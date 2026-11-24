"""Pasqal QPU backend for real quantum hardware execution.

This backend implements neutral-atom MIS solving on real Pasqal QPU hardware:
1. Device discovery via Pasqal Cloud SDK
2. Compilation against real device specifications with pre-calibrated layouts
3. Explicit cost consent before submission
4. Single-attempt job submission with persistence for recovery
5. Transparent weight encoding mode (classical ranking, not physical encoding)

The backend requires:
- Pasqal Cloud credentials
- Explicit device selection via requested_device_id
- Explicit cost consent (_cost_consent=True)
- Positive shot count

Weights are used only for classical ranking of samples, not physically
encoded in the Hamiltonian.
"""

from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

from qreduce.artifacts.metadata import sha256_hex
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
from qreduce.solving.mwis.presolve import PresolveStatus, try_presolve
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason

# Payload version for QPU jobs
QPU_PAYLOAD_VERSION = 1
QPU_RADIUS_UM = 10.0
QPU_MARGIN_UM = 1.0

# Polling intervals for QPU (may be longer than emulator)
DEFAULT_QPU_POLL_INTERVAL_SECONDS = 5.0
MAX_QPU_POLL_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Discovered QPU device information."""

    device_id: str
    name: str
    max_atoms: int
    min_atom_distance: float
    interaction_coeff: float
    has_calibrated_layouts: bool
    available_layouts: tuple[str, ...]
    max_runs: int | None
    status: str
    requires_layout: bool | None = None
    accepts_new_layouts: bool | None = None


def _sdk_available() -> tuple[bool, str | None]:
    """Check if Pulser SDK is available for compilation."""
    try:
        from pulser import Register  # noqa: F401
        from pulser.devices import AnalogDevice  # noqa: F401

        return True, None
    except ImportError:
        return False, "Pulser SDK is unavailable. Install with: poetry install --with experiments"


def _cloud_sdk_available() -> tuple[bool, str | None]:
    """Check if pasqal-cloud SDK is available for QPU execution."""
    try:
        from pasqal_cloud import PasqalCloudConnection  # noqa: F401

        return True, None
    except ImportError:
        return False, "pasqal-cloud SDK is unavailable. Install with: poetry install --with experiments"


def _get_sdk_version() -> str:
    """Get the installed pasqal-cloud version."""
    try:
        return version("pasqal-cloud")
    except PackageNotFoundError:
        return "unknown"


def _sanitize_sdk_error(_error: Exception) -> str:
    """Never expose uncontrolled provider exception messages."""
    return "Pasqal SDK operation failed (details redacted)."


class PasqalQPUMISBackend:
    """Neutral-atom MIS backend for real Pasqal QPU hardware.

    This backend:
    1. Discovers available QPU devices from Pasqal Cloud
    2. Compiles MIS graphs against device specifications with pre-calibrated layouts
    3. Requires explicit cost consent before submission
    4. Submits jobs via Pasqal Cloud with persistent batch_id for recovery
    5. Returns raw samples for classical ranking by MWIS weight

    Weight handling:
    - Weights are NOT physically encoded in the Hamiltonian
    - The backend solves unweighted MIS (all nodes have equal "weight")
    - Weights are used only for classical ranking of samples post-execution
    - This is explicitly declared as WeightEncodingMode.CLASSICAL_RANKING

    Optional compilation parameters:
    - pasqal_profile: Profile name for credentials (default: "default")
    - layout_id: Pre-calibrated layout to use (default: auto-select)

    Required execution parameters:
    - shots: Number of measurements (required, no default)
    - _cost_consent: Explicit acknowledgment before a remote batch can be created
    """

    provider_id = "pasqal"
    backend_id = "pasqal_qpu"

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
            supports_compilation_time_limit=True,  # Cooperative search deadline
            supports_async_execution=False,  # Pipeline uses synchronous solve()
            supports_cancellation=False,
            supports_local_simulator=False,
            supports_remote_qpu=True,
            requires_geometric_mapping=True,
            requires_device_mapping=True,
            required_credentials=True,
            supported_parameter_names=frozenset({"shots", "_cost_consent"}),
            supported_compilation_parameter_names=frozenset({
                "pasqal_profile",
                "layout_id",
                "layout_mode",
            }),
            required_sdk="pasqal-cloud",
            supported_device_ids=None,  # Dynamic via discovery, validated in compile()
            maximum_variables=None,  # Device-specific
            runtime_terminal_reason=None if available else TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
            diagnostic_message=diagnostic,
        )

    def discover_devices(
        self,
        *,
        profile: str = "default",
        timeout_seconds: float = 30.0,
    ) -> tuple[list[DeviceInfo], str | None]:
        """Discover available QPU devices from Pasqal Cloud.

        Returns:
            Tuple of (devices, error_message). On success, error_message is None.
            On failure, devices is empty and error_message describes the problem.
        """
        import os

        if os.getenv("PASQAL_SKIP_SSL_VERIFY"):
            return [], "PASQAL_SKIP_SSL_VERIFY is set. QReduce refuses to connect with TLS verification disabled."

        cloud_available, cloud_diagnostic = _cloud_sdk_available()
        if not cloud_available:
            return [], cloud_diagnostic

        tls = ExitStack()
        try:
            from pasqal_cloud import PasqalCloudConnection

            credentials = resolve_pasqal_credentials(profile=profile)
            tls.enter_context(pasqal_ca_environment())
            connection = PasqalCloudConnection(
                username=credentials.username,
                password=credentials.password,
                project_id=credentials.project_id,
            )

            # Fetch available devices - returns dict[str, pulser.devices.Device]
            devices_dict = connection.fetch_available_devices()
            devices: list[DeviceInfo] = []

            for device_id, pulser_device in devices_dict.items():
                # Only include QPU devices, not emulators
                if device_id.startswith("EMU_"):
                    continue

                # Extract device specs from Pulser Device object
                max_atoms = getattr(pulser_device, "max_atom_num", 100)
                min_dist = getattr(pulser_device, "min_atom_distance", 4.0)
                interaction = getattr(pulser_device, "interaction_coeff", 862690.0)
                max_runs = getattr(pulser_device, "max_runs", None)

                # Check for pre-calibrated layouts (Pulser Device attribute)
                layout_names = tuple(pulser_device.calibrated_register_layouts)

                devices.append(DeviceInfo(
                    device_id=device_id,
                    name=getattr(pulser_device, "name", device_id),
                    max_atoms=max_atoms,
                    min_atom_distance=min_dist,
                    interaction_coeff=interaction,
                    has_calibrated_layouts=len(layout_names) > 0,
                    available_layouts=layout_names,
                    max_runs=max_runs,
                    status="available",  # Device is available if returned by API
                    requires_layout=getattr(pulser_device, "requires_layout", None),
                    accepts_new_layouts=getattr(pulser_device, "accepts_new_layouts", None),
                ))

            return devices, None

        except PasqalCredentialsError:
            return [], "Pasqal credentials unavailable; check the environment or configured profile."
        except CloudTLSConfigurationError as error:
            return [], str(error)
        except Exception:  # noqa: BLE001 - normalize provider failures
            return [], "Failed to discover Pasqal devices (details redacted)."
        finally:
            tls.close()

    def compile(self, problem, request):
        """Compile graph for QPU execution with device-specific validation.

        Compilation flow:
        1. Validate cost consent
        2. Check for exact presolve (edgeless graphs)
        3. If presolve applies, return special payload with presolve result
        4. Discover and validate target device
        5. Build Pulser sequence targeting specific device specs
        6. Validate mapping against device constraints
        """
        start = perf_counter()
        caps = self.capabilities()
        validation = validate_compilation_request(problem, request, caps)

        def fail(reason: TerminalReason, message: str, *, details=None) -> MISCompilationResult:
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
                diagnostic_details=details,
            )

        if not validation.is_valid:
            return fail(
                validation.terminal_reason or TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "; ".join(i.message for i in validation.issues),
            )

        # Validate internal parameters
        params = dict(request.compilation_parameters)

        # QPU requires explicit device selection
        if request.requested_device_id is None:
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "QPU backend requires explicit device selection via requested_device_id.",
            )

        profile = params.get("pasqal_profile", "default")
        layout_id = params.get("layout_id")
        layout_mode = params.get("layout_mode", "calibrated")
        if layout_mode not in ("calibrated", "custom") or (layout_mode == "custom" and layout_id is not None):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_mode must be calibrated or custom; layout_id is only valid in calibrated mode.",
            )

        # Validate layout_id if provided
        if layout_id is not None and not isinstance(layout_id, str):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_id must be a string.",
            )

        # Check for exact presolve opportunity (edgeless graphs)
        presolve_result = try_presolve(problem.graph, requested_backend_id=self.backend_id)

        if presolve_result.status == PresolveStatus.APPLIED:
            # Edgeless graph: return presolve result without QPU submission
            elapsed = perf_counter() - start
            payload = {
                "presolve_applied": True,
                "presolve_reason": presolve_result.reason.value if presolve_result.reason else None,
                "presolve_delta": list(presolve_result.delta) if presolve_result.delta else None,
                "presolve_weight": presolve_result.selection_weight,
                "presolve_size": presolve_result.num_selected,
                "is_certified_optimal": presolve_result.is_certified_optimal,
                "node_order": list(request.node_order),
                "target": "qpu_presolve",
                "device_id": request.requested_device_id,
                "sdk_version": "presolve",
                "weight_encoding_mode": WeightEncodingMode.NOT_APPLICABLE.value,
            }
            job = CompiledMISJob(
                compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-qpu-presolve",
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
                provider_payload_type="pasqal.qpu.presolve",
                provider_payload_version=QPU_PAYLOAD_VERSION,
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

        # Non-trivial graph: proceed with QPU compilation
        # First discover and validate the target device
        import os

        if os.getenv("PASQAL_SKIP_SSL_VERIFY"):
            return fail(
                TerminalReason.MIS_EXECUTION_FAILED,
                "PASQAL_SKIP_SSL_VERIFY is set. QReduce refuses to connect with TLS verification disabled.",
            )

        cloud_available, cloud_diagnostic = _cloud_sdk_available()
        if not cloud_available:
            return fail(TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE, cloud_diagnostic or "Cloud SDK unavailable")

        tls = ExitStack()
        device_info: DeviceInfo | None = None

        try:
            from pasqal_cloud import PasqalCloudConnection

            credentials = resolve_pasqal_credentials(profile=profile)
            tls.enter_context(pasqal_ca_environment())
            connection = PasqalCloudConnection(
                username=credentials.username,
                password=credentials.password,
                project_id=credentials.project_id,
            )

            # Fetch devices - returns dict[str, pulser.devices.Device]
            devices_dict = connection.fetch_available_devices()

            # Find the requested device
            if request.requested_device_id not in devices_dict:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    f"Device '{request.requested_device_id}' not found or not accessible.",
                )

            # Check if device is a QPU (not emulator)
            if request.requested_device_id.startswith("EMU_"):
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    f"Device '{request.requested_device_id}' is an emulator, not a QPU. Use pasqal_cloud_emulator instead.",
                )

            # Get the Pulser Device object - this is a real pulser.devices.Device
            pulser_device = devices_dict[request.requested_device_id]

            # Extract device specifications from Pulser Device
            max_atoms = getattr(pulser_device, "max_atom_num", 100)
            min_dist = getattr(pulser_device, "min_atom_distance", 4.0)
            interaction = getattr(pulser_device, "interaction_coeff", 862690.0)
            max_runs = getattr(pulser_device, "max_runs", None)

            # Get pre-calibrated layouts from the Pulser Device
            calibrated_layouts = pulser_device.calibrated_register_layouts
            layout_names = tuple(calibrated_layouts.keys())

            device_info = DeviceInfo(
                device_id=request.requested_device_id,
                name=getattr(pulser_device, "name", request.requested_device_id),
                max_atoms=max_atoms,
                min_atom_distance=min_dist,
                interaction_coeff=interaction,
                has_calibrated_layouts=len(layout_names) > 0,
                available_layouts=layout_names,
                max_runs=max_runs,
                status="available",
            )

            # Validate atom count
            if len(problem.graph.node_ids) > device_info.max_atoms:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    f"Graph has {len(problem.graph.node_ids)} nodes but device supports max {device_info.max_atoms} atoms.",
                )

            if layout_id is not None and layout_id not in calibrated_layouts:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    f"Layout '{layout_id}' not available on device. Available: {', '.join(layout_names) or 'none'}.",
                    details={"outcome": "no_layouts", "layout_id": layout_id},
                )

            if layout_mode == "custom" and getattr(pulser_device, "accepts_new_layouts", False) is not True:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    "The selected device does not advertise support for custom layouts.",
                    details={"layout_mode": "custom", "outcome": "custom_layout_not_supported"},
                )

            if layout_mode == "calibrated" and not calibrated_layouts:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    "Device has no pre-calibrated layouts. QPU requires calibrated trap positions.",
                )

        except PasqalCredentialsError:
            return fail(
                TerminalReason.MIS_CREDENTIALS_UNAVAILABLE,
                "Pasqal credentials unavailable; check the environment or configured profile.",
            )
        except CloudTLSConfigurationError as error:
            return fail(TerminalReason.MIS_EXECUTION_FAILED, str(error))
        except Exception:  # noqa: BLE001 - normalize provider failures
            return fail(
                TerminalReason.MIS_COMPILATION_FAILED,
                "Failed to access Pasqal device information (details redacted).",
            )
        finally:
            tls.close()

        # Now build the Pulser sequence using the actual QPU device and pre-calibrated layout
        try:
            from importlib.metadata import version as get_version
            from math import dist as euclidean_dist

            from qreduce.solving.mwis.pasqal_mapping import diagnose_layout
            from qreduce.solving.mwis.pasqal_trap_mapping import (
                TrapLayout,
                TrapMappingOutcome,
                search_trap_mapping,
            )
            from qreduce.solving.mwis.pulse_strategy import (
                build_pulse_sequence,
                default_smoothed_annealing_config,
                diagnose_pulse_strategy,
            )

            if not problem.graph.node_ids:
                raise ValueError("empty graph is unsupported")

            num_nodes = len(problem.graph.node_ids)

            compile_budget = request.residual_time_budget_seconds
            compile_deadline = start + compile_budget if compile_budget > 0 else None
            layout_rejections: list[dict[str, str]] = []
            candidate_rejections: dict[str, int] = {}
            trap_layouts: list[TrapLayout] = []

            def timed_out() -> bool:
                return compile_deadline is not None and perf_counter() >= compile_deadline

            layouts_to_search = calibrated_layouts if layout_mode == "calibrated" else {}
            for lid, layout in sorted(layouts_to_search.items()):
                if layout_id is not None and layout_id != lid:
                    continue
                if timed_out():
                    return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, "Compilation timed out.",
                                details={"outcome": "timeout", "rejected_layouts": layout_rejections})
                if num_nodes > layout.number_of_traps:
                    layout_rejections.append({"layout_id": lid, "reason": "insufficient_traps"})
                    continue
                try:
                    pulser_device.validate_layout(layout)
                    pulser_device.validate_layout_filling(layout.make_mappable_register(num_nodes))
                except ValueError as error:
                    layout_rejections.append({"layout_id": lid, "reason": type(error).__name__})
                    continue
                trap_layouts.append(TrapLayout(lid, dict(layout.traps_dict)))

            if layout_mode == "calibrated" and not trap_layouts:
                return fail(
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    "No calibrated layout meets the graph size and device layout constraints.",
                    details={"outcome": "no_eligible_layouts", "rejected_layouts": layout_rejections},
                )

            qubit_ids = [f"q{i}" for i in range(num_nodes)]

            def accept_register(lid: str, assignment: dict[str, int]) -> bool:
                nonlocal register, register_coords, diag
                trap_ids = [assignment[node] for node in problem.graph.node_ids]
                candidate = calibrated_layouts[lid].define_register(*trap_ids, qubit_ids=qubit_ids)
                try:
                    pulser_device.validate_register(candidate)
                except ValueError:
                    candidate_rejections[lid] = candidate_rejections.get(lid, 0) + 1
                    return False
                coordinates = {
                    node: tuple(map(float, candidate.qubits[qubit]))
                    for node, qubit in zip(problem.graph.node_ids, qubit_ids, strict=True)
                }
                diagnostic = diagnose_layout(problem.graph, coordinates, QPU_RADIUS_UM, QPU_MARGIN_UM)
                if not diagnostic["valid"]:
                    candidate_rejections[lid] = candidate_rejections.get(lid, 0) + 1
                    return False
                register, register_coords, diag = candidate, coordinates, diagnostic
                return True

            register = register_coords = diag = None
            if layout_mode == "custom":
                from qreduce.solving.mwis.pasqal_custom_layout import generate_custom_layout

                custom = generate_custom_layout(problem.graph, pulser_device, radius=QPU_RADIUS_UM,
                                                margin=QPU_MARGIN_UM, deadline=compile_deadline)
                mapping_details = custom.details
                register = custom.register
                if register is None:
                    outcome = mapping_details["outcome"]
                    message = {
                        "timeout": "Custom layout generation timed out.",
                        "incompatible_spacing": "Device minimum spacing exceeds the graph edge limit.",
                        "budget_exceeded": "No valid custom layout found within the attempt budget.",
                    }[outcome]
                    return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, message, details=mapping_details)
                register_coords = {
                    node: tuple(map(float, register.qubits[qubit]))
                    for node, qubit in zip(problem.graph.node_ids, qubit_ids, strict=True)
                }
                diag = diagnose_layout(problem.graph, register_coords, QPU_RADIUS_UM, QPU_MARGIN_UM)
            else:
                mapping_result = search_trap_mapping(
                    graph=problem.graph, layouts=trap_layouts, radius=QPU_RADIUS_UM,
                    margin=QPU_MARGIN_UM, min_atom_distance=device_info.min_atom_distance,
                    state_budget_per_layout=100_000, deadline=compile_deadline, accept=accept_register,
                )
                mapping_details = {
                    **mapping_result.to_dict(),
                    "state_budget_per_layout": 100_000,
                    "rejected_layouts": layout_rejections,
                    "rejected_candidates_by_layout": candidate_rejections,
                }
                if timed_out() or mapping_result.outcome == TrapMappingOutcome.TIMEOUT:
                    return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, "Trap mapping search timed out.",
                                details={**mapping_details, "outcome": "timeout"})
                if mapping_result.outcome != TrapMappingOutcome.FOUND:
                    message = {
                        TrapMappingOutcome.EXHAUSTED: "No valid trap mapping exists in the searched layouts.",
                        TrapMappingOutcome.BUDGET_EXCEEDED: "Trap mapping search exceeded state budget.",
                    }.get(mapping_result.outcome, "Trap mapping request could not be completed.")
                    return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, message, details=mapping_details)

            assert register is not None and register_coords is not None and diag is not None
            assignment = mapping_details["assignment"]
            assert isinstance(assignment, dict)
            from dataclasses import replace as dataclass_replace

            pulse_config = default_smoothed_annealing_config()
            if problem.graph.edges:
                max_edge_dist = max(euclidean_dist(register_coords[a], register_coords[b])
                                    for a, b in problem.graph.edges)
                min_edge_interaction = device_info.interaction_coeff / (max_edge_dist ** 6)
                pulse_config = dataclass_replace(
                    pulse_config,
                    final_detuning_rad_per_us=min(pulse_config.final_detuning_rad_per_us, 0.5 * min_edge_interaction),
                )
            try:
                seq = build_pulse_sequence(pulse_config, register, pulser_device)
                seq.measure("ground-rydberg")
                sequence_repr = seq.to_abstract_repr()
                restored = type(seq).from_abstract_repr(sequence_repr)
                if not restored.is_measured():
                    raise ValueError("Serialized QPU sequence is not measured.")
                if layout_mode == "custom":
                    restored_layout = restored.register.layout
                    if (restored_layout is None
                            or sha256_hex(restored_layout.coords.tolist()) != mapping_details["layout_sha256"]
                            or tuple(restored.register.qubit_ids) != tuple(qubit_ids)
                            or list(restored_layout.get_traps_from_coordinates(*restored.register.qubits.values()))
                            != [assignment[n] for n in request.node_order]):
                        raise ValueError("Serialized custom sequence does not preserve the validated register.")
                min_dist_actual = min((euclidean_dist(register_coords[a], register_coords[b])
                                       for i, a in enumerate(problem.graph.node_ids)
                                       for b in problem.graph.node_ids[i + 1:]), default=None)
                pulse_diagnostics = diagnose_pulse_strategy(pulse_config, min_distance_um=min_dist_actual)
            except Exception:  # noqa: BLE001 - sequence/configuration is not a mapping failure
                return fail(TerminalReason.MIS_COMPILATION_FAILED, "QPU sequence construction or validation failed.",
                            details={**mapping_details, "outcome": "sequence_invalid"})
            if timed_out():
                return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, "QPU compilation timed out.",
                            details={**mapping_details, "outcome": "timeout"})

            # Build payload with QPU-specific information
            payload = {
                "presolve_applied": False,
                "sequence_abstract_repr": sequence_repr,
                "sequence_sha256": sha256(sequence_repr.encode()).hexdigest(),
                "target": "qpu",
                "device_id": device_info.device_id,
                "device_name": device_info.name,
                "device_max_atoms": device_info.max_atoms,
                "device_min_distance": device_info.min_atom_distance,
                "device_interaction_coeff": device_info.interaction_coeff,
                "device_max_runs": device_info.max_runs,
                "device_spec_sha256": sha256(pulser_device.to_abstract_repr().encode()).hexdigest(),
                "layout_mode": layout_mode,
                "layout_id": mapping_details["layout_id"],
                "layout_sha256": mapping_details.get("layout_sha256"),
                "trap_ids": [assignment[n] for n in request.node_order],
                "node_to_trap": assignment,
                "node_order": list(request.node_order),
                "coordinates": [list(register_coords[n]) for n in request.node_order],
                "mapping_result": mapping_details,
                "mapping_diagnostic": diag,
                "mapping": diag,  # Legacy alias for test compatibility
                "pulser_rejected_layouts": layout_rejections,
                "sdk_version": _get_sdk_version(),
                "pulser_version": get_version("pulser-core"),
                "weight_encoding_mode": WeightEncodingMode.CLASSICAL_RANKING.value,
                "pulse_strategy": pulse_config.to_dict(),
                "pulse_diagnostics": pulse_diagnostics.to_dict(),
                "min_interatomic_distance_um": min_dist_actual,
                "pasqal_profile": profile,
                "project_id": credentials.project_id,
            }

        except (ValueError, TypeError) as error:
            return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, str(error))
        except Exception:  # noqa: BLE001 - normalize provider failures
            return fail(
                TerminalReason.MIS_COMPILATION_FAILED,
                "QPU compilation failed (details redacted).",
            )

        elapsed = perf_counter() - start
        job = CompiledMISJob(
            compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-qpu",
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
            effective_device_id=f"qpu:{device_info.device_id}",
            runtime_seconds=elapsed,
            effective_compilation_parameters=params,
            capabilities_snapshot=caps,
            provider_payload_type="pasqal.qpu.sequence",
            provider_payload_version=QPU_PAYLOAD_VERSION,
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
        """Execute compiled job: return presolve result or submit to QPU.

        For presolve jobs, returns the deterministic result immediately.
        For QPU jobs:
        1. Validate cost consent
        2. Establish connection with credentials
        3. Verify device specs haven't changed since compilation
        4. Submit sequence to QPU
        5. Persist batch_id before polling (for recovery)
        6. Poll for results with timeout
        7. Decode and return raw samples
        """
        start = perf_counter()
        caps = self.capabilities()
        shots = request.execution_parameters.get("shots")

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

        # QPU requires explicit shots
        if shots is None:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "QPU backend requires explicit shots parameter.",
            )

        # Validate execution parameters
        if (
            set(request.execution_parameters) - {"shots", "_cost_consent"}
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
        if compiled_job.provider_payload_type == "pasqal.qpu.presolve":
            expected = try_presolve(compiled_job.compiled_problem.graph, requested_backend_id=self.backend_id)
            if (
                compiled_job.provider_payload_version != QPU_PAYLOAD_VERSION
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
        # QPU execution path
        # =====================================================================

        # Check pasqal-cloud SDK availability
        cloud_available, cloud_diagnostic = _cloud_sdk_available()
        if not cloud_available:
            return result(
                [],
                TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                cloud_diagnostic,
            )

        # Validate payload
        if (
            compiled_job.provider_payload_type != "pasqal.qpu.sequence"
            or compiled_job.provider_payload_version != QPU_PAYLOAD_VERSION
            or not isinstance(payload, Mapping)
            or payload.get("target") != "qpu"
            or payload.get("node_order") != list(compiled_job.node_order)
            or payload.get("presolve_applied") is not False
        ):
            return result([], TerminalReason.MIS_EXECUTION_FAILED, "Invalid QPU payload.")

        device_id = payload.get("device_id")
        if (not isinstance(device_id, str) or not device_id or device_id.startswith("EMU_")
                or compiled_job.effective_device_id != f"qpu:{device_id}"):
            return result([], TerminalReason.MIS_EXECUTION_FAILED, "Missing device_id in payload.")

        # Consent belongs to the execution request, never to a preflight artifact.
        cost_consent = request.execution_parameters.get("_cost_consent")
        if cost_consent is not True:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "QPU execution requires explicit cost consent in the execution request.",
            )

        # Check max_runs limit
        max_runs = payload.get("device_max_runs")
        if max_runs is not None and shots > max_runs:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"Requested {shots} shots but device allows max {max_runs} runs per job.",
            )

        if self._job_reference_directory is None:
            return result([], TerminalReason.MIS_EXECUTION_FAILED, "A durable Pasqal job reference directory is required.")

        profile = payload.get("pasqal_profile", "default")
        batch_id: str | None = None
        budget = request.residual_time_budget_seconds
        deadline = start + budget if budget > 0 else None
        phase = "prepare"

        from qreduce.solving.mwis.pasqal_cloud_submission import (
            SubmissionOutcomeUnknown,
            SubmissionRejected,
            create_batch_once,
        )

        tls = ExitStack()
        try:
            import os

            from pasqal_cloud import PasqalCloudConnection

            if os.getenv("PASQAL_SKIP_SSL_VERIFY"):
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "PASQAL_SKIP_SSL_VERIFY is set. QReduce refuses to connect with TLS verification disabled.",
                )

            from qreduce.solving.mwis.pasqal_cloud_persistence import (
                prepare_job_reference_directory,
            )

            prepare_job_reference_directory(self._job_reference_directory)
            credentials = resolve_pasqal_credentials(profile=profile)

            # Verify project matches
            compiled_project = payload.get("project_id")
            project_digest = payload.get("project_id_sha256")
            if ((compiled_project and compiled_project != credentials.project_id)
                    or (project_digest is not None
                        and project_digest != sha256(credentials.project_id.encode()).hexdigest())):
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "Configured project does not match compilation project. Re-run preflight.",
                )

            tls.enter_context(pasqal_ca_environment())
            phase = "connect"
            connection = PasqalCloudConnection(
                username=credentials.username,
                password=credentials.password,
                project_id=credentials.project_id,
            )

            # Verify device is still available with same specs
            phase = "verify_device"
            devices_dict = connection.fetch_available_devices()

            if device_id not in devices_dict:
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    f"Device '{device_id}' is no longer available. Re-run preflight.",
                )

            # Get the Pulser Device and check if specs have changed
            pulser_device = devices_dict[device_id]
            current_max_runs = getattr(pulser_device, "max_runs", None)
            current_spec = sha256(pulser_device.to_abstract_repr().encode()).hexdigest()
            if current_spec != payload.get("device_spec_sha256"):
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "QPU specifications changed since compilation. Re-run preflight.",
                )

            if current_max_runs is not None and shots > current_max_runs:
                return result(
                    [],
                    TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                    f"Requested {shots} shots but device now allows max {current_max_runs} runs.",
                )

            # Submit to QPU
            phase = "submit"
            from pulser import Sequence

            sequence_repr = payload["sequence_abstract_repr"]
            if (("sequence_sha256" in payload or payload.get("layout_mode") == "custom")
                    and sha256(sequence_repr.encode()).hexdigest() != payload.get("sequence_sha256")):
                return result([], TerminalReason.MIS_EXECUTION_FAILED, "Compiled sequence hash mismatch.")
            seq = Sequence.from_abstract_repr(sequence_repr)

            # Create batch for QPU - use the SDK's batch creation
            # For QPU, shots are specified via 'runs' in the job
            from time import time

            submission_timestamp = time()
            atom_order = tuple(seq.register.qubit_ids)

            # Build the batch payload for QPU
            if not seq.is_measured():
                if "sequence_sha256" in payload:
                    return result([], TerminalReason.MIS_EXECUTION_FAILED, "Saved QPU sequence is not measured.")
                seq = type(seq).from_abstract_repr(seq.to_abstract_repr())
                seq.measure("ground-rydberg")
                sequence_repr = seq.to_abstract_repr()  # Legacy compiled payloads

            batch_payload = {
                "sequence_builder": sequence_repr,
                "webhook": None,
                "jobs": [{"runs": shots}],  # QPU uses 'runs' field for shots
                "open": False,
                "device_type": device_id,
                "project_id": credentials.project_id,
            }

            batch_id = create_batch_once(connection.cloud_client._client, batch_payload, deadline=deadline)

            # Persist job reference before polling
            phase = "persist"
            from datetime import UTC, datetime

            from qreduce.solving.mwis.pasqal_cloud_persistence import (
                PasqalCloudJobReference,
                save_job_reference,
            )

            reference = PasqalCloudJobReference(
                batch_id=batch_id,
                emulator_service="qpu",  # Mark as QPU job
                project_id=credentials.project_id,
                compiled_job_id=compiled_job.compiled_job_id,
                run_id=request.run_id,
                round_index=request.round_index,
                node_order=compiled_job.node_order,
                shots=shots,
                atom_to_node_map={
                    atom: node for atom, node in zip(atom_order, compiled_job.node_order, strict=True)
                },
                submission_timestamp=datetime.fromtimestamp(submission_timestamp, tz=UTC).isoformat(),
                pasqal_profile=profile,
                sdk_version=_get_sdk_version(),
                target_type="qpu",
                device_id=device_id,
            )

            try:
                save_job_reference(reference, self._job_reference_directory)
            except Exception:  # noqa: BLE001
                # Persistence failed but batch was submitted
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    f"Pre-polling persistence failed. Batch submitted with ID: {batch_id}. Manual recovery possible.",
                    effective_params={"shots": shots, "batch_id": batch_id, "persistence_failed": True},
                )

            # Poll for completion
            phase = "poll"
            from qreduce.solving.mwis.pasqal_cloud_submission import wait_for_completion

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
                    f"QPU batch failed with status {poll_result.status}. Batch ID: {batch_id}",
                    effective_params={"shots": shots, "batch_id": batch_id, "status": poll_result.status},
                )

            # Read results
            phase = "read_results"
            from qreduce.solving.mwis.pasqal_cloud_submission import read_batch_results

            # For QPU, we need to handle differently - check for QPU-specific result format
            batch_results = read_batch_results(
                batch_id, connection, expected_project=credentials.project_id, expected_shots=shots,
                expected_device_type=device_id,  # Pass QPU device ID for validation
            )

            if deadline is not None and perf_counter() >= deadline:
                raise TimeoutError

            # Decode to samples
            phase = "decode"
            from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
                PasqalCloudEmulatorService,
            )
            from qreduce.solving.mwis.pasqal_cloud_submission import (
                decode_results_to_samples,
            )

            weight_encoding = payload.get("weight_encoding_mode", WeightEncodingMode.CLASSICAL_RANKING.value)

            # Create a placeholder service value for QPU
            # We'll need to handle QPU results differently
            samples = decode_results_to_samples(
                batch_results=batch_results,
                node_order=compiled_job.node_order,
                compiled_job_id=compiled_job.compiled_job_id,
                service=PasqalCloudEmulatorService.EMU_FREE,  # Placeholder, will be overridden
                compilation_params=compiled_job.effective_compilation_parameters,
                weight_encoding_mode=weight_encoding,
                atom_to_node_map=dict(zip(atom_order, compiled_job.node_order, strict=True)),
            )

            # Update samples to reflect QPU source
            updated_samples = []
            for sample in samples:
                updated_samples.append(RawMISSample(
                    raw_sample_id=sample.raw_sample_id.replace("pasqal_cloud_emulator", "pasqal_qpu"),
                    node_order=sample.node_order,
                    delta=sample.delta,
                    occurrence_count=sample.occurrence_count,
                    source_provider_id="pasqal",
                    source_backend_id="pasqal_qpu",
                    effective_compilation_parameters=sample.effective_compilation_parameters,
                    effective_execution_parameters={
                        "shots": batch_results.total_shots,
                        "batch_id": batch_id,
                        "device_id": device_id,
                        "weight_encoding_mode": weight_encoding,
                    },
                ))

            return result(
                updated_samples,
                effective_params={
                    "shots": shots,
                    "effective_shots": batch_results.total_shots,
                    "batch_id": batch_id,
                    "device_id": device_id,
                },
            )

        except SubmissionRejected as error:
            return result(
                [], TerminalReason.MIS_REMOTE_SUBMISSION_FAILED, str(error),
                effective_params={"shots": shots, "status": "submission_rejected", "http_status": error.status_code},
            )
        except SubmissionOutcomeUnknown as error:
            return result(
                [], TerminalReason.MIS_REMOTE_SUBMISSION_FAILED, str(error),
                effective_params={"shots": shots, "status": "submission_outcome_unknown"},
            )
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
            msg = f"QPU execution failed during {phase} (details redacted)."
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
