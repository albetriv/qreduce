"""Tests for Pasqal Cloud emulator backend with simulated client.

These tests verify the backend behavior without requiring actual Pasqal Cloud
credentials or the pasqal-cloud SDK. They use mocks to simulate the SDK behavior.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qreduce.mwis import (
    CanonicalMWISProblem,
    ReductionGraph,
    build_mwis_qubo,
    qubo_to_ising,
)
from qreduce.solving.mwis.contracts import (
    MISBackendRequest,
    MISCompilationRequest,
    MISCompletionStatus,
)
from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
    PAYLOAD_VERSION,
    PasqalCloudEmulatorMISBackend,
    PasqalCloudEmulatorService,
)
from qreduce.solving.mwis.pasqal_cloud_persistence import (
    PasqalCloudJobReference,
    load_job_reference,
    save_job_reference,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm, TerminalReason


def problem():
    """Create a minimal problem with one edge (non-presolve case)."""
    graph = ReductionGraph(
        ("b", "a"),
        {"a": 1, "b": 2},
        (("a", "b"),),
        {("a", "b"): "conflict"},
        "test",
        "1",
    )
    qubo = build_mwis_qubo(graph, 3)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def edgeless_problem(node_count: int = 5):
    """Create an edgeless problem for presolve testing."""
    node_ids = tuple(f"n{i}" for i in range(node_count))
    node_weights = {nid: 1.0 + i * 0.1 for i, nid in enumerate(node_ids)}
    graph = ReductionGraph(
        node_ids,
        node_weights,
        (),  # No edges
        {},
        "test",
        "1",
    )
    qubo = build_mwis_qubo(graph, 3)
    return CanonicalMWISProblem(graph, qubo, qubo_to_ising(qubo))


def cloud_compilation_request(p, service="emu_free"):
    """Create a compilation request for the cloud emulator."""
    return MISCompilationRequest(
        "run",
        0,
        p.graph.node_ids,
        0,
        "pasqal",
        "pasqal_cloud_emulator",
        BackendFamily.NEUTRAL_ATOM,
        ExecutionMode.REMOTE,
        ProblemForm.MIS_GRAPH,
        compilation_parameters={
            "_emulator_service": service,
            "_cost_consent": True,
        },
    )


class TestCapabilities:
    """Test capabilities() method behavior."""

    def test_sdk_unavailable_reports_correctly(self):
        """When Pulser is not installed, capabilities should reflect that.

        Note: This test verifies the _sdk_available() logic by patching it.
        In the actual test environment, Pulser is available.
        """
        backend = PasqalCloudEmulatorMISBackend()

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend._sdk_available"
        ) as mock_sdk:
            mock_sdk.return_value = (False, "Pulser SDK unavailable")

            caps = backend.capabilities()

            assert caps.runtime_available is False
            assert caps.runtime_terminal_reason == TerminalReason.MIS_SDK_DEPENDENCY_UNAVAILABLE

    def test_capabilities_with_pulser_available(self):
        """When Pulser is available, capabilities should allow compilation."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        caps = backend.capabilities()

        assert caps.provider_id == "pasqal"
        assert caps.backend_id == "pasqal_cloud_emulator"
        assert caps.backend_family == BackendFamily.NEUTRAL_ATOM
        assert caps.execution_mode == ExecutionMode.REMOTE
        assert caps.runtime_available is True  # Pulser is available
        assert caps.required_credentials is True

    def test_capabilities_declares_remote_execution(self):
        """Capabilities should declare remote execution mode."""
        backend = PasqalCloudEmulatorMISBackend()
        caps = backend.capabilities()

        assert caps.execution_mode == ExecutionMode.REMOTE
        assert caps.required_credentials is True
        assert caps.required_sdk == "pasqal-cloud"


class TestCompilationValidations:
    """Test compile() method validations.

    Note: These tests require Pulser SDK to be available because the backend
    validates SDK availability before other parameters. When SDK is unavailable,
    the first error will always be SDK_DEPENDENCY_UNAVAILABLE.
    """

    def test_missing_emulator_service_rejected(self):
        """Compilation without _emulator_service should fail."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = problem()
        request = replace(
            cloud_compilation_request(p),
            compilation_parameters={"_cost_consent": True},  # Missing service
        )
        result = backend.compile(p, request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert result.terminal_reason == TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
        assert "_emulator_service" in result.diagnostic_message

    def test_emu_free_requires_no_cost_consent(self):
        """EMU_FREE compiles without synthetic consent."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = problem()
        request = replace(
            cloud_compilation_request(p),
            compilation_parameters={"_emulator_service": "emu_free"},  # Missing consent
        )
        result = backend.compile(p, request)

        assert result.completion_status == MISCompletionStatus.COMPLETED

    def test_invalid_emulator_service_rejected(self):
        """Compilation with unknown service should fail."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = problem()
        request = replace(
            cloud_compilation_request(p),
            compilation_parameters={
                "_emulator_service": "unknown_service",
                "_cost_consent": True,
            },
        )
        result = backend.compile(p, request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert "unsupported" in result.diagnostic_message.lower()

    def test_presolve_does_not_resolve_credentials(self):
        pytest.importorskip("pulser")
        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem()
        with patch("qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials") as resolve:
            result = backend.compile(p, cloud_compilation_request(p))
            assert result.completion_status == MISCompletionStatus.COMPLETED
            job = result.compiled_job
            request = MISBackendRequest("run", 0, job.compiled_job_id, p.graph.node_ids, None, 100, 60.0)
            assert backend.solve(job, request).completion_status == MISCompletionStatus.COMPLETED
        resolve.assert_not_called()


class TestPresolve:
    """Test presolve behavior for edgeless graphs."""

    def test_presolve_edgeless_graph(self):
        """Edgeless graphs should be presolved without cloud submission."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem(5)

        # Mock credentials to pass validation
        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )

            result = backend.compile(p, cloud_compilation_request(p))

        assert result.completion_status == MISCompletionStatus.COMPLETED
        job = result.compiled_job

        # Should use presolve path
        assert job.provider_payload_type == "pasqal.cloud.presolve"
        assert job.provider_payload["presolve_applied"] is True
        assert job.provider_payload["presolve_size"] == 5
        assert job.provider_payload["is_certified_optimal"] is True
        assert job.effective_backend_id == "presolve_exact"

    def test_presolve_execution_returns_optimal(self):
        """Solving a presolved job should return the optimal solution."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem(5)

        # Mock credentials
        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )

            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job
        execution = MISBackendRequest(
            "run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0
        )
        result = backend.solve(job, execution)

        assert result.completion_status == MISCompletionStatus.COMPLETED
        assert len(result.samples) == 1

        sample = result.samples[0]
        assert sample.delta == (1, 1, 1, 1, 1)  # All selected
        assert sample.occurrence_count == 1  # Deterministic result
        assert sample.source_provider_id == "qreduce"


class TestPersistence:
    """Test job reference persistence and recovery."""

    def test_save_and_load_job_reference(self, tmp_path):
        """Job references should be persistable and recoverable."""
        reference = PasqalCloudJobReference(
            batch_id="test-batch-123",
            emulator_service="emu_free",
            project_id="test-project",
            compiled_job_id="test:round:0:pasqal-cloud-emu",
            run_id="test",
            round_index=0,
            node_order=("a", "b", "c"),
            shots=100,
            atom_to_node_map={"q0": "a", "q1": "b", "q2": "c"},
            submission_timestamp="2026-11-23T10:00:00Z",
            pasqal_profile="default",
            sdk_version="0.24.0",
        )

        path = save_job_reference(reference, tmp_path)
        assert path.exists()

        loaded = load_job_reference(path)
        assert loaded.batch_id == reference.batch_id
        assert loaded.node_order == reference.node_order
        assert loaded.shots == reference.shots
        assert loaded.project_id == reference.project_id
        assert loaded.atom_to_node_map == reference.atom_to_node_map

    def test_job_reference_to_dict(self):
        """Job reference should be JSON-serializable."""
        reference = PasqalCloudJobReference(
            batch_id="test-batch-123",
            emulator_service="emu_free",
            project_id="test-project",
            compiled_job_id="test:round:0:pasqal-cloud-emu",
            run_id="test",
            round_index=0,
            node_order=("a", "b"),
            shots=50,
            atom_to_node_map={"q0": "a", "q1": "b"},
            submission_timestamp="2026-11-23T10:00:00Z",
            pasqal_profile="default",
            sdk_version="0.24.0",
            job_ids=("job-1", "job-2"),
        )

        data = reference.to_dict()
        assert data["batch_id"] == "test-batch-123"
        assert data["node_order"] == ["a", "b"]
        assert data["job_ids"] == ["job-1", "job-2"]
        assert data["project_id"] == "test-project"
        assert data["atom_to_node_map"] == {"q0": "a", "q1": "b"}

        # Round-trip through dict
        recovered = PasqalCloudJobReference.from_dict(data)
        assert recovered == reference


class TestSolveValidations:
    """Test solve() method validations."""

    def test_job_identity_mismatch_rejected(self):
        """Solve should reject mismatched job identity."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem(5)

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job
        bad_request = MISBackendRequest(
            "WRONG_RUN_ID", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0
        )
        result = backend.solve(job, bad_request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert result.terminal_reason == TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH
        assert "identity" in result.diagnostic_message.lower()

    def test_invalid_shots_rejected(self):
        """Solve should reject invalid shots parameter."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem(5)

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job
        bad_request = MISBackendRequest(
            "run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0,
            execution_parameters={"shots": 0}
        )
        result = backend.solve(job, bad_request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert result.terminal_reason == TerminalReason.MIS_BACKEND_CAPABILITY_MISMATCH

    def test_random_seed_rejected(self):
        """Solve should reject random_seed parameter."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem(5)

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job
        bad_request = MISBackendRequest(
            "run", 0, job.compiled_job_id, p.graph.node_ids,
            random_seed=42,
            requested_solution_count=10,
            residual_time_budget_seconds=0
        )
        result = backend.solve(job, bad_request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert "random_seed" in result.diagnostic_message.lower()


class TestPayloadValidation:
    """Test payload tampering detection."""

    @pytest.mark.parametrize("change", [
        {"presolve_delta": [0, 0, 0, 0, 0]},
        {"is_certified_optimal": False},
        {"node_order": []},
        {"presolve_weight": 999},
        {"presolve_size": 0},
    ])
    def test_presolve_rejects_tampered_payload(self, change):
        """Tampered presolve payloads should be rejected."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem()

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job
        job = replace(job, provider_payload={**job.provider_payload, **change})
        request = MISBackendRequest(
            "run", 0, job.compiled_job_id, p.graph.node_ids, None, 10, 0
        )
        result = backend.solve(job, request)

        assert result.completion_status == MISCompletionStatus.FAILED


class TestEmulatorServiceEnum:
    """Test PasqalCloudEmulatorService enum."""

    def test_emu_free_value(self):
        """EMU_FREE should have correct value."""
        assert PasqalCloudEmulatorService.EMU_FREE.value == "emu_free"

    def test_service_from_string(self):
        """Should be able to create service from string."""
        service = PasqalCloudEmulatorService("emu_free")
        assert service == PasqalCloudEmulatorService.EMU_FREE


class TestSecuritySanitization:
    """Test that secrets are not leaked in error messages."""

    def test_sdk_error_sanitization(self):
        """SDK errors with potential secrets should be sanitized."""
        from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
            _sanitize_sdk_error,
        )

        # Error containing password
        error = Exception("Connection failed: password=secret123")
        sanitized = _sanitize_sdk_error(error)
        assert "secret123" not in sanitized
        assert "redacted" in sanitized.lower()

        # Error containing token
        error = Exception("Auth failed: Bearer eyJhbGciOiJIUzI1NiJ9...")
        sanitized = _sanitize_sdk_error(error)
        assert "eyJ" not in sanitized

        # Safe error message
        error = Exception("Network timeout after 30s")
        sanitized = _sanitize_sdk_error(error)
        assert "unlabelled-value-42" not in _sanitize_sdk_error(Exception("unlabelled-value-42"))
        assert "redacted" in sanitized.lower()


class TestPayloadVersion:
    """Test payload version handling."""

    def test_payload_version_is_defined(self):
        """Payload version should be defined."""
        assert PAYLOAD_VERSION >= 1

    def test_presolve_payload_includes_version(self):
        """Presolve compilation should include payload version."""
        pytest.importorskip("pulser")

        backend = PasqalCloudEmulatorMISBackend()
        p = edgeless_problem()

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        assert compiled.compiled_job.provider_payload_version == PAYLOAD_VERSION


class TestCloudTransportSafety:
    def test_tls_verification_required(self, tmp_path, monkeypatch):
        """Cloud execution should refuse if TLS verification is disabled."""
        pytest.importorskip("pulser")
        pytest.importorskip("pasqal_cloud")

        backend = PasqalCloudEmulatorMISBackend(job_reference_directory=tmp_path)
        p = problem()

        # Set the dangerous environment variable
        monkeypatch.setenv("PASQAL_SKIP_SSL_VERIFY", "1")

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            compiled = backend.compile(p, cloud_compilation_request(p))

        job = compiled.compiled_job

        # Execution should fail due to TLS check
        execution_request = MISBackendRequest(
            "run", 0, job.compiled_job_id, p.graph.node_ids, None, 100, 60.0,
        )

        with patch(
            "qreduce.solving.mwis.pasqal_cloud_emulator_backend.resolve_pasqal_credentials"
        ) as mock_creds:
            mock_creds.return_value = SimpleNamespace(
                username="test", password="test", project_id="test"
            )
            result = backend.solve(job, execution_request)

        assert result.completion_status == MISCompletionStatus.FAILED
        assert "PASQAL_SKIP_SSL_VERIFY" in result.diagnostic_message
