"""Verify that public protocol methods have docstrings.

This test compensates for Ruff exclusions on contract files by directly
checking that Protocol methods critical for API consumers are documented.
"""

import inspect


def _get_protocol_methods(cls: type) -> list[str]:
    """Return public method names defined on a Protocol class (excluding dunder)."""
    methods = []
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if callable(attr) and not isinstance(attr, type):
            methods.append(name)
    return methods


def _check_docstrings(cls: type) -> list[str]:
    """Return names of public methods without docstrings."""
    missing = []
    for name in _get_protocol_methods(cls):
        method = getattr(cls, name, None)
        if method is None:
            continue
        # For Protocol methods, check the function object
        func = method if inspect.isfunction(method) else getattr(method, "__func__", None)
        if func is None:
            continue
        if not func.__doc__:
            missing.append(name)
    return missing


class TestDomainContractDocstrings:
    """Verify ReducibleProblemAdapter methods have docstrings."""

    def test_reducible_problem_adapter_methods_documented(self):
        from qreduce.domains.contracts import ReducibleProblemAdapter

        missing = _check_docstrings(ReducibleProblemAdapter)
        assert not missing, f"ReducibleProblemAdapter methods missing docstrings: {missing}"

    def test_reducible_problem_adapter_class_documented(self):
        from qreduce.domains.contracts import ReducibleProblemAdapter

        assert ReducibleProblemAdapter.__doc__, "ReducibleProblemAdapter class needs a docstring"


class TestClassicalBackendDocstrings:
    """Verify ClassicalBackend protocol methods have docstrings."""

    def test_classical_backend_methods_documented(self):
        from qreduce.solving.residual.contracts import ClassicalBackend

        missing = _check_docstrings(ClassicalBackend)
        assert not missing, f"ClassicalBackend methods missing docstrings: {missing}"

    def test_classical_backend_class_documented(self):
        from qreduce.solving.residual.contracts import ClassicalBackend

        assert ClassicalBackend.__doc__, "ClassicalBackend class needs a docstring"


class TestMISBackendDocstrings:
    """Verify MISExecutionAdapter protocol methods have docstrings."""

    def test_mis_execution_adapter_methods_documented(self):
        from qreduce.solving.mwis.compilation import MISExecutionAdapter

        missing = _check_docstrings(MISExecutionAdapter)
        assert not missing, f"MISExecutionAdapter methods missing docstrings: {missing}"

    def test_mis_execution_adapter_class_documented(self):
        from qreduce.solving.mwis.compilation import MISExecutionAdapter

        assert MISExecutionAdapter.__doc__, "MISExecutionAdapter class needs a docstring"


class TestModelProviderDocstrings:
    """Verify ClassicalModelProvider protocol has docstrings."""

    def test_classical_model_provider_methods_documented(self):
        from qreduce.solving.residual.model import ClassicalModelProvider

        missing = _check_docstrings(ClassicalModelProvider)
        assert not missing, f"ClassicalModelProvider methods missing docstrings: {missing}"

    def test_classical_model_provider_class_documented(self):
        from qreduce.solving.residual.model import ClassicalModelProvider

        assert ClassicalModelProvider.__doc__, "ClassicalModelProvider class needs a docstring"


class TestExperimentAdapterDocstrings:
    """Verify experiment adapters have docstrings on all public methods."""

    def test_portfolio_adapter_methods_documented(self):
        from qreduce.experiments.portfolio_mv.adapter import (
            MeanVariancePortfolioAdapter,
        )

        missing = _check_docstrings(MeanVariancePortfolioAdapter)
        assert not missing, f"MeanVariancePortfolioAdapter methods missing docstrings: {missing}"

    def test_portfolio_adapter_class_documented(self):
        from qreduce.experiments.portfolio_mv.adapter import (
            MeanVariancePortfolioAdapter,
        )

        assert MeanVariancePortfolioAdapter.__doc__, "MeanVariancePortfolioAdapter needs a docstring"

    def test_facility_location_adapter_methods_documented(self):
        from qreduce.experiments.facility_location.adapter import (
            FacilityLocationAdapter,
        )

        missing = _check_docstrings(FacilityLocationAdapter)
        assert not missing, f"FacilityLocationAdapter methods missing docstrings: {missing}"

    def test_facility_location_adapter_class_documented(self):
        from qreduce.experiments.facility_location.adapter import (
            FacilityLocationAdapter,
        )

        assert FacilityLocationAdapter.__doc__, "FacilityLocationAdapter needs a docstring"
