"""Pulser local MIS sample generator with parametric annealing.

This backend implements neutral-atom MIS solving with:
1. Exact presolve for trivially solvable graphs (edgeless)
2. Parametric pulse strategies (smoothed annealing default)
3. Transparent weight encoding mode (classical ranking, not physical encoding)
4. Geometry diagnostics for interaction fidelity

Weights are used only for classical ranking of samples, not physically
encoded in the Hamiltonian. This is explicitly declared in the audit
metadata to maintain transparency.
"""

from collections.abc import Mapping
from dataclasses import replace
from importlib.metadata import version
from time import perf_counter

from qreduce.capabilities import RuntimeCapabilities
from qreduce.solving.mwis.audit import WeightEncodingMode
from qreduce.solving.mwis.compilation import validate_compilation_request
from qreduce.solving.mwis.contracts import (
    CompiledMISJob,
    MISBackendResult,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.solving.mwis.geometry_diagnostics import (
    compare_physical_vs_canonical,
    diagnose_geometry_fidelity,
)
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout, search_layout
from qreduce.solving.mwis.presolve import PresolveStatus, try_presolve
from qreduce.solving.mwis.pulse_strategy import (
    build_pulse_sequence,
    default_smoothed_annealing_config,
    diagnose_pulse_strategy,
    legacy_constant_config,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason

LOCAL_QUTIP_MAX_ATOMS = 12

# Payload version: increment when changing payload structure
PAYLOAD_VERSION = 3  # v3 validates presolve identity/content and physical compilation.


class PasqalLocalMISBackend:
    """Neutral-atom MIS backend with parametric annealing and exact presolve.

    Key improvements over the legacy constant-pulse backend:
    1. Exact presolve for edgeless graphs (100% accuracy, no backend needed)
    2. Smoothed annealing schedule for proper adiabatic evolution
    3. Transparent audit trail distinguishing backend samples from presolve

    Weight handling:
    - Weights are NOT physically encoded in the Hamiltonian
    - The backend solves unweighted MIS (all nodes have equal "weight")
    - Weights are used only for classical ranking of samples post-execution
    - This is explicitly declared as WeightEncodingMode.CLASSICAL_RANKING
    """

    provider_id = "pasqal"
    backend_id = "pasqal_local"

    def capabilities(self):
        """Probe the optional SDK and declare only supported execution controls."""
        try:
            from pulser import Register  # noqa: F401
            from pulser.backend import BitStrings, EmulationConfig  # noqa: F401
            from pulser_simulation import QutipBackendV2  # noqa: F401

            available = True
        except (ImportError, AttributeError):
            available = False
        return RuntimeCapabilities(
            provider_id=self.provider_id,
            backend_id=self.backend_id,
            backend_family=BackendFamily.NEUTRAL_ATOM,
            execution_mode=ExecutionMode.LOCAL,
            runtime_available=available,
            supported_problem_forms=frozenset({ProblemForm.MIS_GRAPH}),
            supports_random_seed=False,
            supports_solution_count=True,
            supports_execution_time_limit=False,
            supports_compilation_time_limit=False,
            supports_async_execution=False,
            supports_cancellation=False,
            supports_local_simulator=True,
            requires_geometric_mapping=True,
            supported_parameter_names=frozenset({"shots"}),
            supported_compilation_parameter_names=frozenset(
                {"layout_attempts", "layout_seed", "use_legacy_pulse", "allow_unfaithful_physics"}
            ),
            required_sdk="pulser",
            maximum_variables=LOCAL_QUTIP_MAX_ATOMS,
            runtime_terminal_reason=None
            if available
            else TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
            diagnostic_message=None
            if available
            else "Pulser local SDK is unavailable or incompatible.",
        )

    def compile(self, problem, request):
        """Compile graph to Pulser sequence with presolve check and parametric annealing.

        Compilation flow:
        1. Check for exact presolve (edgeless graphs)
        2. If presolve applies, return special payload with presolve result
        3. Otherwise, build parametric annealing sequence (default: smoothed)
        4. Use legacy constant pulse only if explicitly requested
        """
        start = perf_counter()
        caps = self.capabilities()
        validation = validate_compilation_request(problem, request, caps)

        def fail(reason, message):
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
                validation.terminal_reason,
                "; ".join(i.message for i in validation.issues),
            )
        if (
            request.requested_device_id not in (None, "AnalogDevice")
            or request.residual_time_budget_seconds > 0
        ):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Unsupported target or compilation time limit.",
            )
        params = request.compilation_parameters
        attempts = params.get("layout_attempts", 1000)
        seed = params.get("layout_seed", 0)
        use_legacy_pulse = params.get("use_legacy_pulse", False)

        if isinstance(seed, bool) or not isinstance(seed, int):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_seed must be an integer.",
            )

        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            return fail(TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH, "layout_attempts must be a positive integer.")
        if not isinstance(use_legacy_pulse, bool) or not isinstance(params.get("allow_unfaithful_physics", False), bool):
            return fail(TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH, "Pulse and experimental flags must be boolean.")

        # Check for exact presolve opportunity (edgeless graphs)
        presolve_result = try_presolve(
            problem.graph, requested_backend_id=self.backend_id
        )

        if presolve_result.status == PresolveStatus.APPLIED:
            # Edgeless graph: return presolve result without backend execution
            elapsed = perf_counter() - start
            payload = {
                "presolve_applied": True,
                "presolve_reason": presolve_result.reason.value if presolve_result.reason else None,
                "presolve_delta": list(presolve_result.delta) if presolve_result.delta else None,
                "presolve_weight": presolve_result.selection_weight,
                "presolve_size": presolve_result.num_selected,
                "is_certified_optimal": presolve_result.is_certified_optimal,
                "node_order": list(request.node_order),
                "target": "AnalogDevice",
                "sdk_version": "presolve",
                "weight_encoding_mode": WeightEncodingMode.NOT_APPLICABLE.value,
            }
            job = CompiledMISJob(
                compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-presolve",
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
                provider_payload_type="pasqal.presolve",
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

        # Non-trivial graph: proceed with Pulser compilation
        try:
            from pulser import Register
            from pulser.devices import AnalogDevice

            if not problem.graph.node_ids:
                raise ValueError("empty graph is unsupported by Pulser")
            if (
                AnalogDevice.max_atom_num is not None
                and len(problem.graph.node_ids) > AnalogDevice.max_atom_num
            ):
                return fail(
                    TerminalReason.MIS_DEVICE_MAPPING_FAILED,
                    "target_atom_limit_exceeded",
                )

            def make_register(coords):
                return Register(
                    {
                        f"q{i}": coords[node]
                        for i, node in enumerate(problem.graph.node_ids)
                    }
                )

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

            # Select pulse strategy
            if use_legacy_pulse:
                pulse_config = legacy_constant_config()
            else:
                pulse_config = default_smoothed_annealing_config()

            # Set a conservative edge penalty scale; residual non-edge effects are
            # checked exhaustively below, not assumed away by this pairwise bound.
            if not use_legacy_pulse:
                from math import dist
                min_edge = min(AnalogDevice.interaction_coeff / dist(coords[a], coords[b]) ** 6
                               for a, b in problem.graph.edges)
                pulse_config = replace(pulse_config, final_detuning_rad_per_us=min(
                    pulse_config.final_detuning_rad_per_us, 0.5 * min_edge))
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
            pulse_diagnostics = diagnose_pulse_strategy(
                pulse_config, min_distance_um=min_dist
            )
            pulse_diagnostics = replace(pulse_diagnostics, device_compatible=True)

            # Get geometry diagnostics: analyze interaction fidelity
            # Uses the final detuning as threshold for significant interaction
            geometry_diag = diagnose_geometry_fidelity(
                problem.graph,
                coords,
                interaction_threshold=pulse_config.final_detuning_rad_per_us,
                c6_coefficient=AnalogDevice.interaction_coeff,
                include_pair_details=False,  # Keep payload size small
            )

            # Compare physical Hamiltonian ground state vs canonical MWIS optimum
            # Only for small graphs where full enumeration is tractable
            physical_comparison = compare_physical_vs_canonical(
                problem.graph,
                coords,
                pulse_config.final_detuning_rad_per_us,
                c6_coefficient=AnalogDevice.interaction_coeff,
                max_enumeration_size=LOCAL_QUTIP_MAX_ATOMS,
            )

            if (physical_comparison is None or not physical_comparison.all_ground_states_independent) and not params.get("allow_unfaithful_physics", False):
                return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED,
                            "Physical diagonal ground states violate independence or could not be verified; experimental override requires allow_unfaithful_physics=true.")
            payload = {
                "physical_validation_scope": "diagonal_only_not_dynamics" if not use_legacy_pulse else "diagonal_only_nonzero_final_amplitude",
                "experimental_physics_override": params.get("allow_unfaithful_physics", False),
                "presolve_applied": False,
                "sequence_abstract_repr": seq.to_abstract_repr(),
                "target": "AnalogDevice",
                "node_order": list(request.node_order),
                "coordinates": [list(coords[n]) for n in request.node_order],
                "mapping": diag,
                "sdk_version": version("pulser-core"),
                "weight_encoding_mode": WeightEncodingMode.CLASSICAL_RANKING.value,
                "pulse_strategy": pulse_config.to_dict(),
                "pulse_diagnostics": pulse_diagnostics.to_dict(),
                "geometry_diagnostics": geometry_diag.to_dict(),
                "physical_vs_canonical": physical_comparison.to_dict() if physical_comparison else None,
                "min_interatomic_distance_um": min_dist,
            }
        except (ValueError, TypeError) as error:
            return fail(TerminalReason.MIS_DEVICE_MAPPING_FAILED, str(error))
        except Exception as error:  # noqa: BLE001 - normalize provider failures at the adapter boundary
            return fail(
                TerminalReason.MIS_COMPILATION_FAILED,
                f"Pulser compilation failed ({type(error).__name__}).",
            )
        elapsed = perf_counter() - start
        job = CompiledMISJob(
            compiled_job_id=f"{request.run_id}:round:{request.round_index}:pasqal-local",
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
            execution_mode=ExecutionMode.LOCAL,
            effective_device_id="AnalogDevice",
            runtime_seconds=elapsed,
            effective_compilation_parameters=params,
            capabilities_snapshot=caps,
            provider_payload_type="pasqal.pulser.sequence",
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

    def solve(self, compiled_job, request):
        """Execute compiled job: return presolve result or run Pulser simulation.

        If the job contains presolve results (edgeless graph), return them directly
        without any simulation. Otherwise, run the Pulser sequence and collect samples.

        Validation order:
        1. Common validations (identity, parameters) apply to BOTH presolve and Pulser paths
        2. SDK availability check applies only to Pulser path
        3. Payload-specific checks apply to respective paths
        """
        start = perf_counter()
        caps = self.capabilities()
        shots = request.execution_parameters.get(
            "shots", request.requested_solution_count
        )

        def result(samples, reason=None, message=None):
            return MISBackendResult(
                samples=tuple(samples),
                requested_provider_id=compiled_job.requested_provider_id,
                requested_backend_id=compiled_job.requested_backend_id,
                effective_provider_id=compiled_job.effective_provider_id,
                effective_backend_id=compiled_job.effective_backend_id,
                backend_family=compiled_job.backend_family,
                execution_mode=ExecutionMode.LOCAL,
                capabilities_snapshot=caps,
                runtime_seconds=perf_counter() - start,
                effective_execution_parameters=({"requested_shots": shots, "effective_shots": 0, "deterministic_result_count": 1} if compiled_job.provider_payload_type == "pasqal.presolve" else {"shots": shots})
                if reason is None
                else request.execution_parameters,
                completion_status=MISCompletionStatus.FAILED
                if reason
                else MISCompletionStatus.COMPLETED,
                terminal_reason=reason,
                diagnostic_message=message,
                effective_device_id=compiled_job.effective_device_id,
            )

        # =====================================================================
        # Common validations for BOTH presolve and Pulser paths
        # =====================================================================

        # Validate job identity
        if (
            request.compiled_job_id != compiled_job.compiled_job_id
            or request.run_id != compiled_job.run_id
            or request.round_index != compiled_job.round_index
            or request.node_order != compiled_job.node_order
            or compiled_job.effective_provider_id != ("qreduce" if compiled_job.provider_payload_type == "pasqal.presolve" else self.provider_id)
            or compiled_job.effective_backend_id not in (self.backend_id, "presolve_exact")
        ):
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Job identity mismatch.",
            )

        # Validate execution parameters (apply to both paths)
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

        # random_seed and time budget not supported by this backend
        if request.random_seed is not None:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Sampling random_seed not supported by this backend.",
            )

        if request.residual_time_budget_seconds > 0:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Execution time budget not supported by this backend.",
            )

        # =====================================================================
        # Handle presolve case (edgeless graph resolved at compile time)
        # =====================================================================
        payload = compiled_job.provider_payload
        if compiled_job.provider_payload_type == "pasqal.presolve":
            expected = try_presolve(compiled_job.compiled_problem.graph, requested_backend_id=self.backend_id)
            if (
                compiled_job.provider_payload_version != PAYLOAD_VERSION
                or expected.status != PresolveStatus.APPLIED
                or not isinstance(payload, Mapping)
                or payload.get("presolve_applied") is not True
                or payload.get("node_order") != list(compiled_job.node_order)
                or payload.get("presolve_delta") != list(expected.delta or ())
                or any(type(bit) is not int for bit in payload.get("presolve_delta", ()))
                or payload.get("presolve_weight") != expected.selection_weight
                or isinstance(payload.get("presolve_weight"), bool)
                or payload.get("presolve_size") != expected.num_selected
                or type(payload.get("presolve_size")) is not int
                or payload.get("is_certified_optimal") is not True
                or payload.get("presolve_reason") != expected.reason.value
            ):
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "Invalid presolve payload.",
                )

            presolve_delta = payload.get("presolve_delta")
            if presolve_delta is None:
                return result(
                    [],
                    TerminalReason.MIS_EXECUTION_FAILED,
                    "Missing presolve delta.",
                )

            # Create single sample from presolve result
            # Note: occurrence_count=1 because this is a deterministic exact result,
            # not a statistical sample from repeated measurements.
            # source_provider_id="qreduce" because this is computed by QReduce's
            # exact presolve algorithm, not by Pasqal/Pulser backend execution.
            sample = RawMISSample(
                raw_sample_id=f"{compiled_job.compiled_job_id}:presolve:exact",
                node_order=compiled_job.node_order,
                delta=tuple(presolve_delta),
                occurrence_count=1,  # Deterministic result, not statistical sample
                source_provider_id="qreduce",  # Computed by QReduce, not Pasqal
                source_backend_id="presolve_exact",
                effective_compilation_parameters=compiled_job.effective_compilation_parameters,
                effective_execution_parameters={
                    "requested_shots": shots,  # Record what was requested
                    "effective_shots": 0,
                    "deterministic_result_count": 1,  # But only 1 deterministic result produced
                    "presolve_reason": payload.get("presolve_reason"),
                    "is_certified_optimal": payload.get("is_certified_optimal", True),
                    "weight_encoding_mode": WeightEncodingMode.NOT_APPLICABLE.value,
                },
                raw_backend_metadata={
                    "presolve_weight": payload.get("presolve_weight"),
                    "presolve_size": payload.get("presolve_size"),
                },
            )
            return result([sample])

        # =====================================================================
        # Standard Pulser simulation path
        # =====================================================================

        # SDK availability (only needed for Pulser, not presolve)
        if not caps.runtime_available:
            return result(
                [],
                TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                caps.diagnostic_message,
            )

        # Atom count limit (only relevant for Pulser simulation)
        if len(compiled_job.node_order) > LOCAL_QUTIP_MAX_ATOMS:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"Local QuTiP limit: {LOCAL_QUTIP_MAX_ATOMS} atoms.",
            )

        try:
            from pulser import Sequence
            from pulser.backend import BitStrings, EmulationConfig
            from pulser_simulation import QutipBackendV2

            if (
                compiled_job.provider_payload_type != "pasqal.pulser.sequence"
                or compiled_job.provider_payload_version != PAYLOAD_VERSION
                or not isinstance(payload, Mapping)
                or payload.get("target") != "AnalogDevice"
                or payload.get("node_order") != list(compiled_job.node_order)
            ):
                raise ValueError("invalid payload")
            seq = Sequence.from_abstract_repr(payload["sequence_abstract_repr"])
            if tuple(seq.register.qubit_ids) != tuple(
                f"q{i}" for i in range(len(compiled_job.node_order))
            ):
                raise ValueError("invalid atom order")
            from pulser.devices import AnalogDevice

            if seq.device != AnalogDevice:
                raise ValueError("invalid device")
            AnalogDevice.validate_register(seq.register)
            coords = {
                node: tuple(float(value) for value in seq.register.qubits[f"q{i}"])
                for i, node in enumerate(compiled_job.node_order)
            }
            if not diagnose_layout(
                compiled_job.compiled_problem.graph, coords, 10.0, 1.0
            )["valid"]:
                raise ValueError("invalid geometry")
            simulation = QutipBackendV2(
                seq,
                config=EmulationConfig(
                    default_num_shots=shots, observables=[BitStrings()]
                ),
            ).run()
            atom_order = tuple(simulation.atom_order)
            expected = tuple(seq.register.qubit_ids)
            if len(atom_order) != len(expected) or set(atom_order) != set(expected):
                raise ValueError("invalid result atom order")
            positions = tuple(atom_order.index(atom) for atom in expected)
            counts = simulation.final_bitstrings
            if sum(counts.values()) != shots:
                raise ValueError("shot count mismatch")

            # Extract pulse strategy info for sample metadata
            weight_encoding = payload.get("weight_encoding_mode", WeightEncodingMode.CLASSICAL_RANKING.value)
            pulse_strategy_info = payload.get("pulse_strategy", {})

            samples = []
            for i, (bits, count) in enumerate(sorted(counts.items())):
                if len(bits) != len(compiled_job.node_order) or set(bits) - {"0", "1"}:
                    raise ValueError("invalid bitstring")
                samples.append(
                    RawMISSample(
                        raw_sample_id=f"{compiled_job.compiled_job_id}:sample:{i:04d}",
                        node_order=compiled_job.node_order,
                        delta=tuple(int(bits[position]) for position in positions),
                        occurrence_count=count,
                        source_provider_id=self.provider_id,
                        source_backend_id=self.backend_id,
                        effective_compilation_parameters=compiled_job.effective_compilation_parameters,
                        effective_execution_parameters={
                            "shots": shots,
                            "weight_encoding_mode": weight_encoding,
                            "pulse_strategy_id": pulse_strategy_info.get("strategy_id"),
                        },
                    )
                )
            return result(samples)
        except Exception as error:  # noqa: BLE001 - normalize provider failures at the adapter boundary
            return result(
                [],
                TerminalReason.MIS_EXECUTION_FAILED,
                f"Pulser execution failed ({type(error).__name__}).",
            )
