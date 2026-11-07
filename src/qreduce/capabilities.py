"""Provider-neutral runtime capability contracts and compatibility validation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from qreduce.config import ValidationIssue, ValidationResult
from qreduce.models import ResolvedRunConfig
from qreduce.status import (
    BackendFamily,
    ExecutionMode,
    ProblemForm,
    TerminalReason,
    UnsupportedBackendParameterPolicy,
)


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Observed backend capability, separate from the requested configuration."""

    provider_id: str
    backend_id: str
    backend_family: BackendFamily
    execution_mode: ExecutionMode
    runtime_available: bool
    supported_problem_forms: frozenset[ProblemForm]
    supports_random_seed: bool
    supports_solution_count: bool
    supports_execution_time_limit: bool
    supports_compilation_time_limit: bool
    supports_async_execution: bool
    supports_cancellation: bool
    supports_local_simulator: bool = False
    supports_remote_qpu: bool = False
    requires_embedding: bool = False
    requires_transpilation: bool = False
    requires_geometric_mapping: bool = False
    requires_device_mapping: bool = False
    supported_parameter_names: frozenset[str] = frozenset()
    required_sdk: str | None = None
    required_credentials: bool = False
    supported_device_ids: frozenset[str] | None = None
    maximum_variables: int | None = None
    runtime_terminal_reason: TerminalReason | None = None
    diagnostic_message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze declared runtime metadata at the capability observation boundary."""

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready representation without runtime SDK objects."""

        from qreduce.artifacts.metadata import to_primitive

        return to_primitive(self)


def validate_backend_compatibility(
    config: ResolvedRunConfig,
    capabilities: RuntimeCapabilities,
    required_problem_form: ProblemForm,
) -> ValidationResult:
    """Reject requested backend/configuration incompatibilities before compilation."""

    selection = config.mis_backend
    execution = config.mis_execution
    issues: list[ValidationIssue] = []

    if not capabilities.runtime_available:
        return ValidationResult.invalid(
            ValidationIssue(
                code="runtime_unavailable",
                field="runtime_available",
                message=capabilities.diagnostic_message or "The requested backend is unavailable.",
            ),
            terminal_reason=capabilities.runtime_terminal_reason
            or TerminalReason.MIS_BACKEND_UNAVAILABLE,
        )
    if selection.provider_id != capabilities.provider_id:
        return _mismatch("provider_id", "Requested MIS provider does not match runtime capability.")
    if selection.backend_id != capabilities.backend_id:
        return _mismatch("backend_id", "Requested MIS backend does not match runtime capability.")
    if selection.backend_family is not capabilities.backend_family:
        return _mismatch("backend_family", "Requested backend family does not match runtime capability.")
    if selection.execution_mode is not capabilities.execution_mode:
        return _mismatch("execution_mode", "Requested execution mode does not match runtime capability.")
    if required_problem_form not in capabilities.supported_problem_forms:
        return ValidationResult.invalid(
            ValidationIssue(
                code="unsupported_problem_form",
                field="required_problem_form",
                message=f"Backend does not support the '{required_problem_form.value}' representation.",
            ),
            terminal_reason=TerminalReason.MIS_PROBLEM_REPRESENTATION_UNSUPPORTED,
        )
    if execution.random_seed is not None and not capabilities.supports_random_seed:
        _add_issue(issues, "random_seed", "A random seed was requested but is unsupported.")
    if execution.requested_solution_count > 1 and not capabilities.supports_solution_count:
        _add_issue(issues, "requested_solution_count", "Multiple requested solutions are unsupported.")
    if execution.execution_time_limit_seconds is not None and not capabilities.supports_execution_time_limit:
        _add_issue(issues, "execution_time_limit_seconds", "Execution time limits are unsupported.")
    if execution.compilation_time_limit_seconds is not None and not capabilities.supports_compilation_time_limit:
        _add_issue(issues, "compilation_time_limit_seconds", "Compilation time limits are unsupported.")
    if (
        selection.device_id is not None
        and capabilities.supported_device_ids is not None
        and selection.device_id not in capabilities.supported_device_ids
    ):
        _add_issue(issues, "device_id", "Requested device is not supported by this backend.")
    unsupported_parameter_names = sorted(
        set(execution.provider_parameters) - set(capabilities.supported_parameter_names)
    )
    if (
        unsupported_parameter_names
        and selection.unsupported_backend_parameter_policy
        is UnsupportedBackendParameterPolicy.REJECT
    ):
        _add_issue(
            issues,
            "provider_parameters",
            "Unsupported backend parameters: " + ", ".join(unsupported_parameter_names) + ".",
        )

    if issues:
        return ValidationResult.invalid(
            *issues,
            terminal_reason=TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
        )
    return ValidationResult.valid()


def _mismatch(field: str, message: str) -> ValidationResult:
    return ValidationResult.invalid(
        ValidationIssue(code="requested_capability_mismatch", field=field, message=message),
        terminal_reason=TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH,
    )


def _add_issue(issues: list[ValidationIssue], field: str, message: str) -> None:
    issues.append(ValidationIssue(code="unsupported_capability", field=field, message=message))