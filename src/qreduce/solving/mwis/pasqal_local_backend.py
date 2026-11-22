"""Pulser local MIS sample generator; weights remain classical pipeline inputs."""

from collections.abc import Mapping
from importlib.metadata import version
from time import perf_counter

from qreduce.capabilities import RuntimeCapabilities
from qreduce.solving.mwis.compilation import validate_compilation_request
from qreduce.solving.mwis.contracts import (
    CompiledMISJob,
    MISBackendResult,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout, search_layout
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason

LOCAL_QUTIP_MAX_ATOMS = 12


class PasqalLocalMISBackend:
    """Strict geometry and a fixed analog heuristic, with no implicit fallback."""

    provider_id = "pasqal"
    backend_id = "pasqal_local"

    def capabilities(self):
        """Probe the optional SDK and declare only supported execution controls."""
        try:
            from pulser import Pulse, Register, Sequence  # noqa: F401
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
                {"layout_attempts", "layout_seed"}
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
        """Validate geometry and serialize a fixed Pulser sequence."""
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
        attempts, seed = (
            params.get("layout_attempts", 1000),
            params.get("layout_seed", 0),
        )
        if isinstance(seed, bool) or not isinstance(seed, int):
            return fail(
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "layout_seed must be an integer.",
            )
        try:
            from pulser import Pulse, Register, Sequence
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
            seq = Sequence(register, AnalogDevice)
            seq.declare_channel("global", "rydberg_global")
            seq.add(Pulse.ConstantPulse(1000, 1.0, 1.0, 0.0), "global")
            payload = {
                "sequence_abstract_repr": seq.to_abstract_repr(),
                "target": "AnalogDevice",
                "node_order": list(request.node_order),
                "coordinates": [list(coords[n]) for n in request.node_order],
                "mapping": diag,
                "sdk_version": version("pulser-core"),
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
            provider_payload_version=1,
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
        """Revalidate and run the serialized sequence, preserving all counts."""
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
                effective_provider_id=self.provider_id,
                effective_backend_id=self.backend_id,
                backend_family=BackendFamily.NEUTRAL_ATOM,
                execution_mode=ExecutionMode.LOCAL,
                capabilities_snapshot=caps,
                runtime_seconds=perf_counter() - start,
                effective_execution_parameters={"shots": shots}
                if reason is None
                else request.execution_parameters,
                completion_status=MISCompletionStatus.FAILED
                if reason
                else MISCompletionStatus.COMPLETED,
                terminal_reason=reason,
                diagnostic_message=message,
                effective_device_id="AnalogDevice",
            )

        if not caps.runtime_available:
            return result(
                [],
                TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                caps.diagnostic_message,
            )
        if (
            request.compiled_job_id != compiled_job.compiled_job_id
            or request.run_id != compiled_job.run_id
            or request.round_index != compiled_job.round_index
            or request.node_order != compiled_job.node_order
            or compiled_job.effective_provider_id != self.provider_id
            or compiled_job.effective_backend_id != self.backend_id
        ):
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Job identity mismatch.",
            )
        if len(compiled_job.node_order) > LOCAL_QUTIP_MAX_ATOMS:
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                f"Local QuTiP limit: {LOCAL_QUTIP_MAX_ATOMS} atoms.",
            )
        if (
            set(request.execution_parameters) - {"shots"}
            or isinstance(shots, bool)
            or not isinstance(shots, int)
            or shots < 1
            or request.random_seed is not None
            or request.residual_time_budget_seconds > 0
        ):
            return result(
                [],
                TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
                "Unsupported execution parameters.",
            )
        try:
            from pulser import Sequence
            from pulser.backend import BitStrings, EmulationConfig
            from pulser_simulation import QutipBackendV2

            payload = compiled_job.provider_payload
            if (
                compiled_job.provider_payload_type != "pasqal.pulser.sequence"
                or compiled_job.provider_payload_version != 1
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
                        effective_execution_parameters={"shots": shots},
                    )
                )
            return result(samples)
        except Exception as error:  # noqa: BLE001 - normalize provider failures at the adapter boundary
            return result(
                [],
                TerminalReason.MIS_EXECUTION_FAILED,
                f"Pulser execution failed ({type(error).__name__}).",
            )
