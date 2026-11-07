"""Tests for lazy CPLEX runtime capability detection."""

from types import ModuleType

from qreduce.classical import cplex_capability


def test_probe_reports_explicit_failure_when_cplex_binding_is_unavailable(
    monkeypatch,
) -> None:
    """A missing optional binding is observable and never triggers a fallback."""

    def raise_import_error(module_name: str) -> ModuleType:
        assert module_name == "cplex"
        raise ModuleNotFoundError("No module named 'cplex'", name="cplex")

    monkeypatch.setattr(cplex_capability, "_import_module", raise_import_error)

    capability = cplex_capability.probe_cplex_runtime()

    assert capability.requested_backend == "cplex"
    assert capability.binding_importable is False
    assert capability.license_environment_available is None
    assert capability.miqp_support_available is None
    assert capability.effective_backend == "unavailable"
    assert capability.terminal_reason == "classical_backend_unavailable"


def test_probe_reports_importable_binding_without_claiming_runtime_readiness(
    monkeypatch,
) -> None:
    """Importability alone does not claim that licensing or MIQP is available."""

    imported_modules: list[str] = []

    def import_cplex(module_name: str) -> ModuleType:
        imported_modules.append(module_name)
        return ModuleType(module_name)

    monkeypatch.setattr(cplex_capability, "_import_module", import_cplex)

    capability = cplex_capability.probe_cplex_runtime()

    assert imported_modules == ["cplex"]
    assert capability.binding_importable is True
    assert capability.license_environment_available is None
    assert capability.miqp_support_available is None
    assert capability.effective_backend == "cplex"
    assert capability.terminal_reason is None


def test_capability_is_serializable_without_cplex_runtime_objects() -> None:
    """Capability data is ready for future artifacts without SDK values."""

    capability = cplex_capability.CplexRuntimeCapability(
        requested_backend="cplex",
        binding_importable=False,
        license_environment_available=None,
        miqp_support_available=None,
        effective_backend="unavailable",
        terminal_reason="classical_backend_unavailable",
        diagnostic_message="The optional CPLEX Python binding is not importable.",
    )

    assert capability.to_dict() == {
        "requested_backend": "cplex",
        "binding_importable": False,
        "license_environment_available": None,
        "miqp_support_available": None,
        "effective_backend": "unavailable",
        "terminal_reason": "classical_backend_unavailable",
        "diagnostic_message": "The optional CPLEX Python binding is not importable.",
    }