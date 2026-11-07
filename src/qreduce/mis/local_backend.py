"""Built-in local greedy MIS backend with deterministic seeded multi-start search."""

import random
from time import perf_counter

from qreduce.capabilities import RuntimeCapabilities
from qreduce.mis.compilation import validate_compilation_request
from qreduce.mis.contracts import (
    BackendReportedScoreKind,
    CompiledMISJob,
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
    MISCompletionStatus,
    RawMISSample,
)
from qreduce.mwis.graph import CanonicalMWISProblem
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


class LocalGreedyMISBackend:
    """Dependency-free heuristic backend; samples are never certified MWIS optima."""

    provider_id = "local"
    backend_id = "greedy_mis"

    def capabilities(self) -> RuntimeCapabilities:
        """Return the actual local backend capability without optional SDK dependencies."""

        return RuntimeCapabilities(
            provider_id=self.provider_id,
            backend_id=self.backend_id,
            backend_family=BackendFamily.CLASSICAL_HEURISTIC,
            execution_mode=ExecutionMode.LOCAL,
            runtime_available=True,
            supported_problem_forms=frozenset({ProblemForm.MIS_GRAPH}),
            supports_random_seed=True,
            supports_solution_count=True,
            supports_execution_time_limit=True,
            supports_compilation_time_limit=True,
            supports_async_execution=False,
            supports_cancellation=False,
            supports_local_simulator=True,
        )

    def compile(
        self,
        problem: CanonicalMWISProblem,
        request: MISCompilationRequest,
    ) -> MISCompilationResult:
        """Create a local graph job after explicit capability and order validation."""

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
            compiled_job_id=f"{request.run_id}:round:{request.round_index}:local-greedy",
            run_id=request.run_id,
            round_index=request.round_index,
            node_order=request.node_order,
            problem_form=ProblemForm.MIS_GRAPH,
            compiled_problem=problem,
            requested_provider_id=request.requested_provider_id,
            requested_backend_id=request.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.CLASSICAL_HEURISTIC,
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
        """Generate dependency-free greedy independent-set samples within the given budget."""

        started_at = perf_counter()
        failure = self._validate_execution_request(compiled_job, request)
        if failure is not None:
            return self._failure_result(compiled_job, request, failure, perf_counter() - started_at)
        random_generator = random.Random(request.random_seed)
        samples: list[RawMISSample] = []
        for attempt_index in range(request.requested_solution_count):
            if perf_counter() - started_at >= request.residual_time_budget_seconds:
                return self._result(
                    compiled_job,
                    request,
                    tuple(samples),
                    perf_counter() - started_at,
                    MISCompletionStatus.TIME_LIMITED,
                    TerminalReason.MIS_EXECUTION_TIME_BUDGET_EXHAUSTED,
                )
            delta = self._greedy_delta(compiled_job.compiled_problem, random_generator)
            samples.append(
                RawMISSample(
                    raw_sample_id=f"{compiled_job.compiled_job_id}:sample:{attempt_index:04d}",
                    node_order=compiled_job.node_order,
                    delta=delta,
                    backend_reported_score=None,
                    backend_reported_score_kind=BackendReportedScoreKind.UNAVAILABLE,
                    source_provider_id=self.provider_id,
                    source_backend_id=self.backend_id,
                    execution_runtime_seconds=perf_counter() - started_at,
                    effective_compilation_parameters=compiled_job.effective_compilation_parameters,
                    effective_execution_parameters=request.execution_parameters,
                    raw_backend_metadata={"algorithm": "seeded_greedy_independent_set"},
                )
            )
        return self._result(
            compiled_job,
            request,
            tuple(samples),
            perf_counter() - started_at,
            MISCompletionStatus.COMPLETED,
            None,
        )

    def _greedy_delta(self, problem: CanonicalMWISProblem, random_generator: random.Random) -> tuple[int, ...]:
        graph = problem.graph
        tie_breakers = {node_id: random_generator.random() for node_id in graph.node_ids}
        ordered_nodes = sorted(
            graph.node_ids,
            key=lambda node_id: (-graph.node_weights[node_id], tie_breakers[node_id], node_id),
        )
        selected_nodes: set[str] = set()
        adjacent_nodes: dict[str, set[str]] = {node_id: set() for node_id in graph.node_ids}
        for left, right in graph.edges:
            adjacent_nodes[left].add(right)
            adjacent_nodes[right].add(left)
        for node_id in ordered_nodes:
            if not selected_nodes.intersection(adjacent_nodes[node_id]):
                selected_nodes.add(node_id)
        return tuple(1 if node_id in selected_nodes else 0 for node_id in graph.node_ids)

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
        if set(request.execution_parameters):
            return TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
        return None

    def _failure_result(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
        reason: TerminalReason,
        runtime_seconds: float,
    ) -> MISBackendResult:
        return self._result(compiled_job, request, (), runtime_seconds, MISCompletionStatus.FAILED, reason)

    def _result(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
        samples: tuple[RawMISSample, ...],
        runtime_seconds: float,
        completion_status: MISCompletionStatus,
        terminal_reason: TerminalReason | None,
    ) -> MISBackendResult:
        return MISBackendResult(
            samples=samples,
            requested_provider_id=compiled_job.requested_provider_id,
            requested_backend_id=compiled_job.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            backend_family=BackendFamily.CLASSICAL_HEURISTIC,
            execution_mode=ExecutionMode.LOCAL,
            capabilities_snapshot=self.capabilities(),
            runtime_seconds=runtime_seconds,
            effective_execution_parameters=request.execution_parameters,
            completion_status=completion_status,
            terminal_reason=terminal_reason,
            effective_device_id=None,
        )