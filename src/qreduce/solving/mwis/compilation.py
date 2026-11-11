"""Adapter protocol and provider-neutral pre-compilation validation."""

from typing import Protocol

from qreduce.capabilities import RuntimeCapabilities
from qreduce.config import ValidationIssue, ValidationResult
from qreduce.mwis.graph import CanonicalMWISProblem
from qreduce.solving.mwis.contracts import (
    CompiledMISJob,
    MISBackendRequest,
    MISBackendResult,
    MISCompilationRequest,
    MISCompilationResult,
)
from qreduce.status import TerminalReason


class MISExecutionAdapter(Protocol):
    """Provider-neutral separation between capability, compilation and execution."""

    def capabilities(self) -> RuntimeCapabilities:
        """Return the adapter's observed runtime capability."""

    def compile(
        self,
        problem: CanonicalMWISProblem,
        request: MISCompilationRequest,
    ) -> MISCompilationResult:
        """Compile a canonical problem into an auditable backend job."""

    def solve(self, compiled_job: CompiledMISJob, request: MISBackendRequest) -> MISBackendResult:
        """Execute a compiled job and return raw auditable samples."""


def validate_compilation_request(
    problem: CanonicalMWISProblem,
    request: MISCompilationRequest,
    capabilities: RuntimeCapabilities,
) -> ValidationResult:
    """Reject incompatible form, identity, node order and real graph size before compilation."""

    if not capabilities.runtime_available:
        return ValidationResult.invalid(
            ValidationIssue("runtime_unavailable", "runtime_available", capabilities.diagnostic_message or "Backend unavailable."),
            terminal_reason=capabilities.runtime_terminal_reason or TerminalReason.MIS_BACKEND_UNAVAILABLE,
        )
    if request.requested_provider_id != capabilities.provider_id:
        return _invalid("requested_provider_id", "Requested provider does not match adapter capability.")
    if request.requested_backend_id != capabilities.backend_id:
        return _invalid("requested_backend_id", "Requested backend does not match adapter capability.")
    if request.requested_backend_family is not capabilities.backend_family:
        return _invalid("requested_backend_family", "Requested backend family does not match adapter capability.")
    if request.requested_execution_mode is not capabilities.execution_mode:
        return _invalid("requested_execution_mode", "Requested execution mode does not match adapter capability.")
    if request.required_problem_form not in capabilities.supported_problem_forms:
        return ValidationResult.invalid(
            ValidationIssue("unsupported_problem_form", "required_problem_form", "Requested representation is unsupported."),
            terminal_reason=TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED,
        )
    if request.node_order != problem.graph.node_ids:
        return _invalid("node_order", "Compilation request node order does not match canonical problem.")
    if capabilities.maximum_variables is not None and len(problem.graph.node_ids) > capabilities.maximum_variables:
        return _invalid("maximum_variables", "Canonical problem exceeds the backend variable limit.")
    if (
        request.requested_device_id is not None
        and capabilities.supported_device_ids is not None
        and request.requested_device_id not in capabilities.supported_device_ids
    ):
        return _invalid("requested_device_id", "Requested device is unsupported.")
    unsupported_parameters = set(request.compilation_parameters) - set(capabilities.supported_parameter_names)
    if unsupported_parameters:
        return _invalid("compilation_parameters", "Unsupported compilation parameters were requested.")
    return ValidationResult.valid()


def _invalid(field: str, message: str) -> ValidationResult:
    return ValidationResult.invalid(
        ValidationIssue("mis_compilation_incompatible", field, message),
        terminal_reason=TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
    )