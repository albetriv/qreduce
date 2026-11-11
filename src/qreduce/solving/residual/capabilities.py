"""Common runtime capability contract for residual classical solvers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassicalRuntimeCapabilities:
    """Observed availability and supported features of one classical solver."""

    solver_id: str
    runtime_available: bool
    supports_milp: bool
    supports_miqp: bool
    supports_random_seed: bool
    supports_threads: bool
    supports_mip_gap: bool
    supports_model_export: bool
    binding_importable: bool
    license_environment_available: bool | None
    diagnostic_message: str | None = None

    def __post_init__(self) -> None:
        if not self.solver_id.strip():
            raise ValueError("solver_id cannot be blank.")