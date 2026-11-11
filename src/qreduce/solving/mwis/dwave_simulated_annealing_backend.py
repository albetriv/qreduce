"""Lazy local D-Wave Ocean simulated-annealing MIS backend."""

from collections.abc import Mapping
from importlib import import_module as _import_module
from operator import index
from time import perf_counter
from typing import Any

from qreduce.capabilities import RuntimeCapabilities
from qreduce.mwis.graph import CanonicalMWISProblem
from qreduce.mwis.validation import MWISValidationError, normalize_binary_vector
from qreduce.solving.mwis.compilation import validate_compilation_request
from qreduce.solving.mwis.contracts import (
    BackendReportedScoreKind,
    CompiledMISJob,
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


class DWaveSimulatedAnnealingMISBackend:
    """Run the local Ocean simulated-annealing sampler over QReduce's canonical QUBO."""

    provider_id = "dwave"
    backend_id = "simulated_annealing"
    _supported_parameter_names = frozenset(
        {"num_reads", "num_sweeps", "beta_range", "beta_schedule_type"}
    )

    def capabilities(self) -> RuntimeCapabilities:
        """Report whether the optional local Ocean sampler is importable."""

        try:
            _load_ocean_runtime()
        except (ImportError, ModuleNotFoundError):
            return RuntimeCapabilities(
                provider_id=self.provider_id,
                backend_id=self.backend_id,
                backend_family=BackendFamily.ANNEALING,
                execution_mode=ExecutionMode.LOCAL,
                runtime_available=False,
                supported_problem_forms=frozenset({ProblemForm.QUBO}),
                supports_random_seed=True,
                supports_solution_count=True,
                supports_execution_time_limit=False,
                supports_compilation_time_limit=False,
                supports_async_execution=False,
                supports_cancellation=False,
                supports_local_simulator=True,
                supported_parameter_names=self._supported_parameter_names,
                required_sdk="dimod and dwave-samplers",
                runtime_terminal_reason=TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                diagnostic_message=(
                    "The optional D-Wave Ocean local simulator requires the "
                    "'dimod' and 'dwave-samplers' packages."
                ),
            )
        return RuntimeCapabilities(
            provider_id=self.provider_id,
            backend_id=self.backend_id,
            backend_family=BackendFamily.ANNEALING,
            execution_mode=ExecutionMode.LOCAL,
            runtime_available=True,
            supported_problem_forms=frozenset({ProblemForm.QUBO}),
            supports_random_seed=True,
            supports_solution_count=True,
            supports_execution_time_limit=False,
            supports_compilation_time_limit=False,
            supports_async_execution=False,
            supports_cancellation=False,
            supports_local_simulator=True,
            supported_parameter_names=self._supported_parameter_names,
            required_sdk="dimod and dwave-samplers",
        )

    def compile(
        self,
        problem: CanonicalMWISProblem,
        request: MISCompilationRequest,
    ) -> MISCompilationResult:
        """Validate a QUBO request and retain the canonical problem for local execution."""

        started_at = perf_counter()
        validation = validate_compilation_request(problem, request, self.capabilities())
        runtime_seconds = perf_counter() - started_at
        if not validation.is_valid:
            return MISCompilationResult(
                compiled_job=None,
                requested_provider_id=request.requested_provider_id,
                requested_backend_id=request.requested_backend_id,
                effective_provider_id=None,
                effective_backend_id=None,
                runtime_seconds=runtime_seconds,
                completion_status=MISCompletionStatus.FAILED,
                terminal_reason=validation.terminal_reason,
                diagnostic_message="; ".join(issue.message for issue in validation.issues),
            )
        job = CompiledMISJob(
            compiled_job_id=f"{request.run_id}:round:{request.round_index}:dwave-simulated-annealing",
            run_id=request.run_id,
            round_index=request.round_index,
            node_order=request.node_order,
            problem_form=ProblemForm.QUBO,
            compiled_problem=problem,
            requested_provider_id=request.requested_provider_id,
            requested_backend_id=request.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.ANNEALING,
            execution_mode=ExecutionMode.LOCAL,
            effective_device_id=None,
            runtime_seconds=runtime_seconds,
            effective_compilation_parameters=request.compilation_parameters,
            capabilities_snapshot=self.capabilities(),
        )
        return MISCompilationResult(
            compiled_job=job,
            requested_provider_id=request.requested_provider_id,
            requested_backend_id=request.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            runtime_seconds=runtime_seconds,
            completion_status=MISCompletionStatus.COMPLETED,
            effective_compilation_parameters=request.compilation_parameters,
        )

    def solve(self, compiled_job: CompiledMISJob, request: MISBackendRequest) -> MISBackendResult:
        """Sample the canonical QUBO and preserve native QUBO energies and occurrences."""

        started_at = perf_counter()
        failure_reason = self._validate_execution_request(compiled_job, request)
        if failure_reason is not None:
            return self._failure_result(compiled_job, request, failure_reason, perf_counter() - started_at)
        try:
            dimod_module, samplers_module = _load_ocean_runtime()
        except (ImportError, ModuleNotFoundError):
            return self._failure_result(
                compiled_job,
                request,
                TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                perf_counter() - started_at,
                "The optional D-Wave Ocean local simulator is no longer importable.",
            )
        try:
            bqm = _build_bqm(dimod_module, compiled_job.compiled_problem)
            effective_parameters = _effective_execution_parameters(request)
            sampleset = samplers_module.SimulatedAnnealingSampler().sample(bqm, **effective_parameters)
            runtime_seconds = perf_counter() - started_at
            samples = _raw_samples(
                compiled_job,
                sampleset,
                request.requested_solution_count,
                runtime_seconds,
                effective_parameters,
            )
        except MWISValidationError as error:
            return self._failure_result(
                compiled_job,
                request,
                TerminalReason.MIS_RESULT_NORMALIZATION_FAILED,
                perf_counter() - started_at,
                str(error),
            )
        except Exception as error:  # noqa: BLE001 - Optional SDK failures must be normalized.
            return self._failure_result(
                compiled_job,
                request,
                TerminalReason.MIS_EXECUTION_FAILED,
                perf_counter() - started_at,
                f"D-Wave simulated annealing execution failed: {type(error).__name__}: {error}",
            )
        return MISBackendResult(
            samples=samples,
            requested_provider_id=compiled_job.requested_provider_id,
            requested_backend_id=compiled_job.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.ANNEALING,
            execution_mode=ExecutionMode.LOCAL,
            capabilities_snapshot=self.capabilities(),
            runtime_seconds=runtime_seconds,
            effective_execution_parameters=effective_parameters,
            completion_status=MISCompletionStatus.COMPLETED,
            effective_device_id=None,
        )

    def _validate_execution_request(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
    ) -> TerminalReason | None:
        if request.compiled_job_id != compiled_job.compiled_job_id:
            return TerminalReason.MIS_EXECUTION_FAILED
        if request.run_id != compiled_job.run_id or request.round_index != compiled_job.round_index:
            return TerminalReason.MIS_EXECUTION_FAILED
        if request.node_order != compiled_job.node_order:
            return TerminalReason.MIS_RESULT_NORMALIZATION_FAILED
        if compiled_job.effective_provider_id != self.provider_id or compiled_job.effective_backend_id != self.backend_id:
            return TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
        if set(request.execution_parameters) - self._supported_parameter_names:
            return TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
        return None

    def _failure_result(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
        reason: TerminalReason,
        runtime_seconds: float,
        diagnostic_message: str | None = None,
    ) -> MISBackendResult:
        return MISBackendResult(
            samples=(),
            requested_provider_id=compiled_job.requested_provider_id,
            requested_backend_id=compiled_job.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.ANNEALING,
            execution_mode=ExecutionMode.LOCAL,
            capabilities_snapshot=self.capabilities(),
            runtime_seconds=runtime_seconds,
            effective_execution_parameters=request.execution_parameters,
            completion_status=MISCompletionStatus.FAILED,
            terminal_reason=reason,
            diagnostic_message=diagnostic_message,
            effective_device_id=None,
        )


def _load_ocean_runtime() -> tuple[Any, Any]:
    """Import the two packages required by the local Ocean simulated annealer lazily."""

    return _import_module("dimod"), _import_module("dwave.samplers")


def _build_bqm(dimod_module: Any, problem: CanonicalMWISProblem) -> Any:
    """Translate QReduce's binary QUBO coefficients without changing variable order."""

    qubo = problem.qubo
    coefficients = {(node_id, node_id): qubo.linear[node_id] for node_id in qubo.node_order}
    coefficients.update(qubo.quadratic)
    return dimod_module.BinaryQuadraticModel.from_qubo(coefficients, offset=qubo.offset)


def _effective_execution_parameters(request: MISBackendRequest) -> dict[str, object]:
    """Combine QReduce standard controls with declared Ocean sampler parameters."""

    parameters = dict(request.execution_parameters)
    parameters.setdefault("num_reads", request.requested_solution_count)
    if request.random_seed is not None:
        parameters["seed"] = request.random_seed
    return parameters


def _raw_samples(
    compiled_job: CompiledMISJob,
    sampleset: Any,
    requested_solution_count: int,
    execution_runtime_seconds: float,
    effective_execution_parameters: dict[str, object],
) -> tuple[RawMISSample, ...]:
    """Convert Ocean SampleSet rows into canonical-order, auditable binary samples."""

    samples: list[RawMISSample] = []
    for sample_index, record in enumerate(
        sampleset.data(fields=["sample", "energy", "num_occurrences"], sorted_by="energy")
    ):
        if sample_index >= requested_solution_count:
            break
        sample = record.sample
        if not isinstance(sample, Mapping):
            raise MWISValidationError(
                "invalid_backend_sample",
                "sample",
                "Ocean sample must be a mapping keyed by canonical node IDs.",
            )
        sample_node_ids = set(sample)
        expected_node_ids = set(compiled_job.node_order)
        missing_node_ids = sorted(expected_node_ids - sample_node_ids)
        extra_node_ids = sorted(sample_node_ids - expected_node_ids)
        if missing_node_ids or extra_node_ids:
            details: list[str] = []
            if missing_node_ids:
                details.append("missing=" + ", ".join(missing_node_ids))
            if extra_node_ids:
                details.append("extra=" + ", ".join(extra_node_ids))
            raise MWISValidationError(
                "backend_sample_node_ids_mismatch",
                "sample",
                "Ocean sample node IDs do not match the canonical node order: " + "; ".join(details),
            )
        delta = _decode_binary_sample_values(sample, compiled_job.node_order)
        samples.append(
            RawMISSample(
                raw_sample_id=f"{compiled_job.compiled_job_id}:sample:{sample_index:04d}",
                node_order=compiled_job.node_order,
                delta=delta,
                occurrence_count=int(record.num_occurrences),
                backend_reported_score=float(record.energy),
                backend_reported_score_kind=BackendReportedScoreKind.QUBO_ENERGY,
                source_provider_id=DWaveSimulatedAnnealingMISBackend.provider_id,
                source_backend_id=DWaveSimulatedAnnealingMISBackend.backend_id,
                execution_runtime_seconds=execution_runtime_seconds,
                effective_compilation_parameters=compiled_job.effective_compilation_parameters,
                effective_execution_parameters=effective_execution_parameters,
                raw_backend_metadata={"sampler": "dwave.samplers.SimulatedAnnealingSampler"},
            )
        )
    return tuple(samples)


def _decode_binary_sample_values(
    sample: Mapping[str, object], node_order: tuple[str, ...]
) -> tuple[int, ...]:
    """Accept provider integer scalars while rejecting floats, booleans and non-binary values."""

    decoded_values: list[int] = []
    for node_id in node_order:
        value = sample[node_id]
        if isinstance(value, bool):
            raise MWISValidationError(
                "invalid_binary_value",
                f"sample[{node_id!r}]",
                "Each Ocean sample value must be the integer 0 or 1, not a boolean.",
            )
        try:
            decoded_values.append(index(value))
        except TypeError as error:
            raise MWISValidationError(
                "invalid_binary_value",
                f"sample[{node_id!r}]",
                "Each Ocean sample value must be an integer scalar equal to 0 or 1.",
            ) from error
    return normalize_binary_vector(tuple(decoded_values), "sample")