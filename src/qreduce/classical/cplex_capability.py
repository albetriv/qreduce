"""Lazy runtime capability detection for the optional CPLEX binding."""

from dataclasses import asdict, dataclass
from importlib import import_module as _import_module
from typing import Literal


@dataclass(frozen=True, slots=True)
class CplexRuntimeCapability:
    """Observed CPLEX runtime state without creating a solver model.

    License/environment and MIQP support stay ``None`` until the concrete CPLEX
    backend defines non-invasive checks for them. The capability probe never
    substitutes a different solver.
    """

    requested_backend: Literal["cplex"]
    binding_importable: bool
    license_environment_available: bool | None
    miqp_support_available: bool | None
    effective_backend: Literal["cplex", "unavailable"]
    terminal_reason: Literal["classical_backend_unavailable"] | None
    diagnostic_message: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-ready representation with primitive values."""

        return asdict(self)


def probe_cplex_runtime() -> CplexRuntimeCapability:
    """Report whether the optional ``cplex`` Python binding can be imported.

    The import is intentionally deferred until this function is called so that
    importing :mod:`qreduce` never requires CPLEX. A successful import alone is
    not evidence of an available license or MIQP support.
    """

    try:
        _import_module("cplex")
    except (ImportError, ModuleNotFoundError):
        return CplexRuntimeCapability(
            requested_backend="cplex",
            binding_importable=False,
            license_environment_available=None,
            miqp_support_available=None,
            effective_backend="unavailable",
            terminal_reason="classical_backend_unavailable",
            diagnostic_message="The optional CPLEX Python binding is not importable.",
        )

    return CplexRuntimeCapability(
        requested_backend="cplex",
        binding_importable=True,
        license_environment_available=None,
        miqp_support_available=None,
        effective_backend="cplex",
        terminal_reason=None,
        diagnostic_message=None,
    )