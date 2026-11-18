"""Lazy local D-Wave Ocean simulated-annealing MIS backend with optional embedding.

This backend supports two execution paths:
- none (default): Direct sampling of the logical BQM
- pegasus_p16/zephyr_z12: Embedding onto hardware-like topology before sampling

The embedding path models connectivity constraints and chain overhead, not quantum
dynamics or actual QPU timing. All operations are local without credentials.

Budget management (cooperative time budget):
-------------------------------------------
When the pipeline provides a compilation time budget (residual_time_budget_seconds > 0),
the backend implements cooperative budget sharing:

1. A monotonic deadline is calculated at the start of compile() as:
   deadline = time.perf_counter() + residual_time_budget_seconds

2. Budget is checked before each expensive operation:
   - Before embedding search
   - After embedding search
   - After chain strength calculation

3. The embedding helper (find_embedding) receives the deadline and recalculates
   remaining time immediately before each internal operation:
   - Before importing libraries
   - Before building target topology
   - Before calling minorminer

4. Execution timing is tracked separately:
   - sampling_time_seconds: physical sampling on embedded BQM
   - decoding_time_seconds: unembedding + conversion to logical samples

This approach ensures accurate budget accounting even when operations complete
faster or slower than expected, and prevents over-allocation when the budget
is nearly exhausted.
"""

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

# Embedding profile constants
EMBEDDING_PROFILE_KEY = "embedding_profile"
EMBEDDING_PROFILE_NONE = "none"


class DWaveSimulatedAnnealingMISBackend:
    """Run the local Ocean simulated-annealing sampler over QReduce's canonical QUBO.

    When an embedding profile is specified in compilation_parameters, the backend:
    1. Builds the logical BQM from the canonical QUBO
    2. Finds an embedding onto the target topology
    3. Embeds the BQM with chain couplings
    4. Samples the embedded BQM with topology-constrained sampler
    5. Decodes physical samples back to logical variables
    6. Returns samples with logical energies

    Supported embedding profiles:
    - none: Direct logical BQM sampling (default)
    - pegasus_p16: Pegasus topology with m=16
    - zephyr_z12: Zephyr topology with m=12
    """

    provider_id = "dwave"
    backend_id = "simulated_annealing"
    _supported_parameter_names = frozenset(
        {"num_reads", "num_sweeps", "beta_range", "beta_schedule_type"}
    )
    _supported_compilation_parameter_names = frozenset({EMBEDDING_PROFILE_KEY})

    def capabilities(self) -> RuntimeCapabilities:
        """Report whether the optional local Ocean sampler is importable.

        The backend supports compilation time limits as a cooperative budget:
        embedding search timeout is capped at min(60s, remaining_budget).
        This is not a hard timeout - minorminer may slightly exceed the limit.
        """
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
                supports_compilation_time_limit=True,  # Cooperative budget for embedding
                supports_async_execution=False,
                supports_cancellation=False,
                supports_local_simulator=True,
                supported_parameter_names=self._supported_parameter_names,
                supported_compilation_parameter_names=self._supported_compilation_parameter_names,
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
            supports_compilation_time_limit=True,  # Cooperative budget for embedding
            supports_async_execution=False,
            supports_cancellation=False,
            supports_local_simulator=True,
            supported_parameter_names=self._supported_parameter_names,
            supported_compilation_parameter_names=self._supported_compilation_parameter_names,
            required_sdk="dimod and dwave-samplers",
        )

    def compile(
        self,
        problem: CanonicalMWISProblem,
        request: MISCompilationRequest,
    ) -> MISCompilationResult:
        """Validate the request and optionally find an embedding.

        For embedding profiles other than 'none', this method:
        1. Builds the logical BQM
        2. Builds the target topology graph
        3. Finds a minor-embedding
        4. Stores embedding metadata in effective_compilation_parameters
        """
        started_at = perf_counter()

        # Validate basic compilation requirements
        validation = validate_compilation_request(problem, request, self.capabilities())
        if not validation.is_valid:
            return MISCompilationResult(
                compiled_job=None,
                requested_provider_id=request.requested_provider_id,
                requested_backend_id=request.requested_backend_id,
                effective_provider_id=None,
                effective_backend_id=None,
                runtime_seconds=perf_counter() - started_at,
                completion_status=MISCompletionStatus.FAILED,
                terminal_reason=validation.terminal_reason,
                diagnostic_message="; ".join(issue.message for issue in validation.issues),
            )

        # Extract and validate embedding profile
        embedding_profile_id = request.compilation_parameters.get(
            EMBEDDING_PROFILE_KEY, EMBEDDING_PROFILE_NONE
        )

        # Validate profile value
        try:
            from qreduce.solving.mwis.dwave_embedding import (
                VALID_EMBEDDING_PROFILES,
                resolve_embedding_profile,
            )
            if embedding_profile_id not in VALID_EMBEDDING_PROFILES:
                return MISCompilationResult(
                    compiled_job=None,
                    requested_provider_id=request.requested_provider_id,
                    requested_backend_id=request.requested_backend_id,
                    effective_provider_id=None,
                    effective_backend_id=None,
                    runtime_seconds=perf_counter() - started_at,
                    completion_status=MISCompletionStatus.FAILED,
                    terminal_reason=TerminalReason.INVALID_CONFIGURATION,
                    diagnostic_message=(
                        f"Invalid embedding profile: {embedding_profile_id!r}. "
                        f"Valid profiles: {', '.join(sorted(VALID_EMBEDDING_PROFILES))}"
                    ),
                )
            profile = resolve_embedding_profile(embedding_profile_id)
        except ImportError:
            # Embedding module not available, only 'none' profile is valid
            if embedding_profile_id != EMBEDDING_PROFILE_NONE:
                return MISCompilationResult(
                    compiled_job=None,
                    requested_provider_id=request.requested_provider_id,
                    requested_backend_id=request.requested_backend_id,
                    effective_provider_id=None,
                    effective_backend_id=None,
                    runtime_seconds=perf_counter() - started_at,
                    completion_status=MISCompletionStatus.FAILED,
                    terminal_reason=TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                    diagnostic_message=(
                        f"Embedding profile '{embedding_profile_id}' requires the "
                        "'dwave-embedding' dependency group."
                    ),
                )
            profile = None

        # Build effective compilation parameters
        effective_params: dict[str, object] = dict(request.compilation_parameters)

        # Initialize embedded_bqm to None (populated only for hardware profiles)
        embedded_bqm = None

        # If embedding is enabled, find the embedding
        if profile is not None and profile.is_embedding_enabled:
            try:
                from qreduce.solving.mwis.dwave_embedding import find_embedding

                dimod_module, _ = _load_ocean_runtime()
                logical_bqm = _build_bqm(dimod_module, problem)

                # Extract seed from compilation parameters (propagated from config)
                embedding_seed = request.compilation_parameters.get("_random_seed")
                if embedding_seed is not None and not isinstance(embedding_seed, int):
                    embedding_seed = None

                # Use monotonic deadline for budget management
                # All time checks use the same reference point
                residual_budget = request.residual_time_budget_seconds
                has_finite_budget = residual_budget > 0
                deadline = started_at + residual_budget if has_finite_budget else None

                def remaining_budget_seconds() -> float:
                    """Calculate remaining budget from monotonic deadline."""
                    if deadline is None:
                        return float("inf")
                    return max(0.0, deadline - perf_counter())

                def check_budget_exhausted(stage: str) -> MISCompilationResult | None:
                    """Return failure result if budget exhausted, None otherwise."""
                    if has_finite_budget and remaining_budget_seconds() <= 0:
                        return MISCompilationResult(
                            compiled_job=None,
                            requested_provider_id=request.requested_provider_id,
                            requested_backend_id=request.requested_backend_id,
                            effective_provider_id=self.provider_id,
                            effective_backend_id=self.backend_id,
                            runtime_seconds=perf_counter() - started_at,
                            completion_status=MISCompletionStatus.FAILED,
                            terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
                            diagnostic_message=f"Compilation time budget exhausted {stage}.",
                            effective_compilation_parameters=effective_params,
                        )
                    return None

                # Check budget before embedding search
                if (exhausted := check_budget_exhausted("before embedding search")) is not None:
                    return exhausted

                # Find embedding with deadline (helper will calculate timeout internally)
                embedding_result = find_embedding(
                    logical_bqm,
                    profile,
                    seed=embedding_seed,
                    deadline=deadline,  # Pass deadline, not timeout
                )

                if not embedding_result.success:
                    return MISCompilationResult(
                        compiled_job=None,
                        requested_provider_id=request.requested_provider_id,
                        requested_backend_id=request.requested_backend_id,
                        effective_provider_id=self.provider_id,
                        effective_backend_id=self.backend_id,
                        runtime_seconds=perf_counter() - started_at,
                        completion_status=MISCompletionStatus.FAILED,
                        terminal_reason=embedding_result.terminal_reason or TerminalReason.MIS_EMBEDDING_FAILED,
                        diagnostic_message=embedding_result.diagnostic_message,
                        effective_compilation_parameters=effective_params,
                    )

                # Check budget after embedding search
                if (exhausted := check_budget_exhausted("after embedding search")) is not None:
                    return exhausted

                # Store embedding result in effective parameters for execution
                effective_params["_embedding"] = embedding_result.embedding
                effective_params["_embedding_profile"] = profile.to_dict()
                effective_params["_embedding_search_result"] = {
                    "topology_node_count": embedding_result.topology_node_count,
                    "topology_edge_count": embedding_result.topology_edge_count,
                    "source_node_count": embedding_result.source_node_count,
                    "source_edge_count": embedding_result.source_edge_count,
                    "embedded_qubit_count": embedding_result.embedded_qubit_count,
                    "mean_chain_length": embedding_result.mean_chain_length,
                    "max_chain_length": embedding_result.max_chain_length,
                    "search_time_seconds": embedding_result.search_time_seconds,
                    "search_timeout_seconds": embedding_result.search_timeout_seconds,
                    "seed_used": embedding_result.seed_used,
                    "library_versions": dict(embedding_result.library_versions),
                }

                # Embed BQM and determine chain strength using uniform_torque_compensation policy
                # This is done here in compile() so solve() uses the pre-embedded BQM directly
                try:
                    from qreduce.solving.mwis.dwave_embedding import (
                        CHAIN_BREAK_METHOD_MAJORITY_VOTE,
                        CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE,
                        CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
                        EMBEDDING_PROFILE_DEFINITION_VERSION,
                        build_target_topology,
                        embed_bqm,
                    )

                    target_graph = build_target_topology(profile)
                    # Pass prefactor explicitly to avoid implicit SDK defaults
                    embedded_bqm, chain_strength = embed_bqm(
                        logical_bqm,
                        embedding_result.embedding,
                        target_graph,
                        prefactor=CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
                    )

                    # Store chain strength metadata at job level (not duplicated per sample)
                    effective_params["_chain_strength_metadata"] = {
                        "profile_definition_version": EMBEDDING_PROFILE_DEFINITION_VERSION,
                        "chain_strength_policy": CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE,
                        "chain_strength_policy_parameters": {
                            "prefactor": CHAIN_STRENGTH_UNIFORM_TORQUE_PREFACTOR,
                        },
                        "chain_strength_value": chain_strength,
                        "chain_break_method": CHAIN_BREAK_METHOD_MAJORITY_VOTE,
                    }

                    # Keep backward-compatible flat keys for simple access
                    effective_params["_chain_strength"] = chain_strength
                    effective_params["_chain_strength_policy"] = CHAIN_STRENGTH_POLICY_UNIFORM_TORQUE

                    # Check budget after embedding
                    if (exhausted := check_budget_exhausted("after embedding")) is not None:
                        return exhausted

                except Exception as error:  # noqa: BLE001
                    return MISCompilationResult(
                        compiled_job=None,
                        requested_provider_id=request.requested_provider_id,
                        requested_backend_id=request.requested_backend_id,
                        effective_provider_id=self.provider_id,
                        effective_backend_id=self.backend_id,
                        runtime_seconds=perf_counter() - started_at,
                        completion_status=MISCompletionStatus.FAILED,
                        terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
                        diagnostic_message=f"Failed to determine chain strength: {error}",
                        effective_compilation_parameters=effective_params,
                    )

            except ImportError as error:
                return MISCompilationResult(
                    compiled_job=None,
                    requested_provider_id=request.requested_provider_id,
                    requested_backend_id=request.requested_backend_id,
                    effective_provider_id=None,
                    effective_backend_id=None,
                    runtime_seconds=perf_counter() - started_at,
                    completion_status=MISCompletionStatus.FAILED,
                    terminal_reason=TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE,
                    diagnostic_message=str(error),
                )
            except Exception as error:  # noqa: BLE001
                return MISCompilationResult(
                    compiled_job=None,
                    requested_provider_id=request.requested_provider_id,
                    requested_backend_id=request.requested_backend_id,
                    effective_provider_id=self.provider_id,
                    effective_backend_id=self.backend_id,
                    runtime_seconds=perf_counter() - started_at,
                    completion_status=MISCompletionStatus.FAILED,
                    terminal_reason=TerminalReason.MIS_COMPILATION_FAILED,
                    diagnostic_message=f"Embedding search failed: {error}",
                    effective_compilation_parameters=effective_params,
                )

        runtime_seconds = perf_counter() - started_at

        # Serialize embedded BQM if present (for hardware profiles)
        embedded_bqm_serialized = None
        if embedded_bqm is not None:
            embedded_bqm_serialized = embedded_bqm.to_serializable()

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
            effective_compilation_parameters=effective_params,
            capabilities_snapshot=self.capabilities(),
            embedded_bqm_serialized=embedded_bqm_serialized,
        )
        return MISCompilationResult(
            compiled_job=job,
            requested_provider_id=request.requested_provider_id,
            requested_backend_id=request.requested_backend_id,
            effective_provider_id=self.provider_id,
            effective_backend_id=self.backend_id,
            runtime_seconds=runtime_seconds,
            completion_status=MISCompletionStatus.COMPLETED,
            effective_compilation_parameters=effective_params,
        )

    def solve(self, compiled_job: CompiledMISJob, request: MISBackendRequest) -> MISBackendResult:
        """Sample the QUBO and return logical samples.

        For embedded problems:
        1. Build the embedded BQM using the stored embedding
        2. Sample with a topology-constrained sampler
        3. Decode physical samples to logical samples with majority vote
        4. Recompute logical energies
        """
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

        # Check if this is an embedded job
        embedding = compiled_job.effective_compilation_parameters.get("_embedding")
        embedding_profile_id = compiled_job.effective_compilation_parameters.get(
            EMBEDDING_PROFILE_KEY, EMBEDDING_PROFILE_NONE
        )

        # Determine if hardware profile requires embedding
        is_hardware_profile = embedding_profile_id not in (None, EMBEDDING_PROFILE_NONE)

        # Validate: hardware profile MUST have valid embedding - no silent fallback
        if is_hardware_profile:
            if embedding is None:
                return self._failure_result(
                    compiled_job,
                    request,
                    TerminalReason.MIS_EMBEDDING_FAILED,
                    perf_counter() - started_at,
                    f"Hardware profile '{embedding_profile_id}' requires embedding but none found in compiled job.",
                )
            if not isinstance(embedding, Mapping) or len(embedding) == 0:
                return self._failure_result(
                    compiled_job,
                    request,
                    TerminalReason.MIS_EMBEDDING_FAILED,
                    perf_counter() - started_at,
                    f"Hardware profile '{embedding_profile_id}' has invalid or empty embedding.",
                )

        try:
            logical_bqm = _build_bqm(dimod_module, compiled_job.compiled_problem)
            effective_parameters = _effective_execution_parameters(request)

            if is_hardware_profile:
                # Embedded execution path - embedding already validated above
                samples, chain_break_stats = self._solve_embedded(
                    compiled_job,
                    request,
                    logical_bqm,
                    embedding,
                    effective_parameters,
                    dimod_module,
                    samplers_module,
                )
                # Add chain break stats to effective parameters for artifact tracking
                effective_parameters = {
                    **effective_parameters,
                    "_chain_break_statistics": chain_break_stats,
                }
            else:
                # Direct logical BQM execution path (profile is 'none' or absent)
                sampleset = samplers_module.SimulatedAnnealingSampler().sample(
                    logical_bqm, **effective_parameters
                )
                samples = _raw_samples(
                    compiled_job,
                    sampleset,
                    request.requested_solution_count,
                    perf_counter() - started_at,
                    effective_parameters,
                )

            runtime_seconds = perf_counter() - started_at

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

    def _solve_embedded(
        self,
        compiled_job: CompiledMISJob,
        request: MISBackendRequest,
        logical_bqm: Any,
        embedding: Mapping[str, tuple[int, ...]],
        effective_parameters: dict[str, object],
        dimod_module: Any,
        samplers_module: Any,
    ) -> tuple[tuple[RawMISSample, ...], dict[str, object]]:
        """Execute sampling on embedded BQM and decode to logical samples.

        Reconstructs the pre-embedded BQM from its serialized form stored in compile().
        No re-embedding or chain strength recalculation needed.
        """
        from qreduce.solving.mwis.dwave_embedding import (
            build_target_topology,
            resolve_embedding_profile,
            unembed_sampleset,
        )

        # Resolve profile to get topology (for StructureComposite)
        embedding_profile_id = compiled_job.effective_compilation_parameters.get(
            EMBEDDING_PROFILE_KEY, EMBEDDING_PROFILE_NONE
        )
        profile = resolve_embedding_profile(embedding_profile_id)
        target_graph = build_target_topology(profile)

        # Retrieve chain strength from compile() - must be present for hardware profiles
        chain_strength = compiled_job.effective_compilation_parameters.get("_chain_strength")
        if chain_strength is None:
            raise ValueError(
                "chain_strength not found in compiled job - compile() must set _chain_strength"
            )

        # Reconstruct embedded BQM from serialized form
        embedded_bqm_serialized = compiled_job.embedded_bqm_serialized
        if embedded_bqm_serialized is None:
            raise ValueError(
                "embedded_bqm_serialized not found in compiled job - "
                "compile() must set embedded_bqm_serialized for hardware profiles"
            )
        embedded_bqm = dimod_module.BinaryQuadraticModel.from_serializable(embedded_bqm_serialized)

        # Sample the embedded BQM using structure-constrained sampler
        # Use dimod.StructureComposite to constrain sampling to target topology
        # No fallback: if StructureComposite is unavailable, fail explicitly
        from dimod import StructureComposite
        structured_sampler = StructureComposite(
            samplers_module.SimulatedAnnealingSampler(),
            target_graph.nodes(),
            target_graph.edges(),
        )

        # Track sampling time separately
        sampling_started = perf_counter()
        embedded_sampleset = structured_sampler.sample(embedded_bqm, **effective_parameters)
        sampling_time_seconds = perf_counter() - sampling_started

        # Track decoding time (unembed + convert to RawMISSamples)
        decoding_started = perf_counter()

        # Unembed to get logical samples
        logical_sampleset, chain_stats = unembed_sampleset(
            embedded_sampleset,
            embedding,
            logical_bqm,
        )

        # Convert to RawMISSamples
        samples = _raw_samples_from_logical_sampleset(
            compiled_job,
            logical_sampleset,
            request.requested_solution_count,
            effective_parameters,
            chain_strength,
            chain_stats,
        )
        decoding_time_seconds = perf_counter() - decoding_started

        # Merge timing into chain stats
        execution_stats = {
            **chain_stats.to_dict(),
            "sampling_time_seconds": sampling_time_seconds,
            "decoding_time_seconds": decoding_time_seconds,
        }

        return samples, execution_stats

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


def _raw_samples_from_logical_sampleset(
    compiled_job: CompiledMISJob,
    sampleset: Any,
    requested_solution_count: int,
    effective_execution_parameters: dict[str, object],
    chain_strength: float,
    chain_stats: Any,
) -> tuple[RawMISSample, ...]:
    """Convert unembedded Ocean SampleSet to canonical RawMISSamples."""
    # Create a "light" version of compilation parameters for samples
    # that excludes large/duplicated data structures
    # The full embedding and chain strength metadata are stored once in
    # compiled_job, not duplicated per-sample
    excluded_keys = {"_embedding", "_chain_strength_metadata"}
    sample_compilation_params: dict[str, object] = {
        k: v for k, v in compiled_job.effective_compilation_parameters.items()
        if k not in excluded_keys
    }

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
                "Unembedded sample must be a mapping keyed by canonical node IDs.",
            )

        # Validate node IDs match
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
                "Unembedded sample node IDs do not match: " + "; ".join(details),
            )

        delta = _decode_binary_sample_values(sample, compiled_job.node_order)

        # Build metadata including embedding info
        backend_metadata: dict[str, object] = {
            "sampler": "dwave.samplers.SimulatedAnnealingSampler",
            "execution_mode": "embedded",
            "chain_strength": chain_strength,
            "chain_break_method": "majority_vote",
        }

        samples.append(
            RawMISSample(
                raw_sample_id=f"{compiled_job.compiled_job_id}:embedded:sample:{sample_index:04d}",
                node_order=compiled_job.node_order,
                delta=delta,
                occurrence_count=int(record.num_occurrences),
                backend_reported_score=float(record.energy),
                backend_reported_score_kind=BackendReportedScoreKind.QUBO_ENERGY,
                source_provider_id=DWaveSimulatedAnnealingMISBackend.provider_id,
                source_backend_id=DWaveSimulatedAnnealingMISBackend.backend_id,
                effective_compilation_parameters=sample_compilation_params,
                effective_execution_parameters=effective_execution_parameters,
                raw_backend_metadata=backend_metadata,
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
