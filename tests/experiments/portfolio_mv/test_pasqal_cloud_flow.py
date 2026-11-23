"""Portfolio MV CLI acceptance with real Pasqal SDK objects, no network."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qreduce.experiments.portfolio_mv import __main__ as cli
from qreduce.solving.mwis import pasqal_cloud_persistence as persistence


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    pytest.importorskip("pasqal_cloud")
    from pasqal_cloud.authentication import PasswordGrantTokenProvider
    from pulser import Sequence
    from pulser.backend import Results
    from requests import Response, Timeout
    from requests.adapters import HTTPAdapter

    monkeypatch.setenv("PASQAL_USERNAME", "fake-user")
    monkeypatch.setenv("PASQAL_PASSWORD", "fake-password")
    monkeypatch.setenv("PASQAL_PROJECT_ID", "fake-project")
    monkeypatch.delenv("PASQAL_SKIP_SSL_VERIFY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "configure_logging", lambda *args: True)
    calls = []
    state = {"status": ["PENDING", "DONE"], "post": 201, "shots": 64}
    journal = tmp_path / ".pasqal-cloud-jobs" / "cloud-run"
    reference = journal / "pasqal_cloud_job_batch-1.json"

    def get_token(_):
        if state.get("check_ca"):
            bundle = Path(os.environ["REQUESTS_CA_BUNDLE"])
            assert bundle.is_file()
            state.setdefault("token_bundles", []).append(bundle)
        return "unlabelled-value-123"

    monkeypatch.setattr(PasswordGrantTokenProvider, "get_token", get_token)

    def send(adapter, request, **kwargs):
        if state.get("check_ca"):
            bundle = Path(kwargs["verify"])
            assert bundle == state["token_bundles"][-1] and bundle.is_file()
        method, url = request.method, request.url
        calls.append((method, url))
        status = 200
        if method == "POST" and url.endswith("/api/v1/batches"):
            assert adapter.max_retries.total == 0
            assert journal.is_dir() and not reference.exists()
            state["payload"] = payload = json.loads(request.body)
            assert payload["jobs"] == [{}]
            assert payload["device_type"] == "EMU_FREE" and payload["open"] is False
            assert payload["project_id"] == "fake-project"
            assert json.loads(payload["backend_configuration"])["default_num_shots"] == state.get("requested_shots", 64)
            assert Sequence.from_abstract_repr(payload["sequence_builder"]).is_measured()
            if state["post"] == "timeout":
                raise Timeout("unlabelled-value-123")
            if state.get("expire_after_post"):
                state["clock"] = 100_000
            status = state["post"]
            data = {"data": {"id": "batch-1"}}
        elif method == "GET":
            assert persistence.load_job_reference(reference).batch_id == "batch-1"
            if url.endswith("/batches/batch-1/status"):
                if state.get("access_denied"):
                    status = 403
                statuses = state["status"]
                data = {"data": {"status": statuses.pop(0) if len(statuses) > 1 else statuses[0]}}
            elif url.endswith("/batches/batch-1"):
                data = {"data": {
                    "id": "batch-1", "project_id": "fake-project", "user_id": "fake-user",
                    "device_type": "EMU_FREE", "status": "DONE", "open": False, "complete": True,
                    "created_at": "2026-11-23", "updated_at": "2026-11-23",
                    "sequence_builder": state["payload"]["sequence_builder"],
                    "jobs": [{"id": "job-1", "batch_id": "batch-1", "project_id": "fake-project",
                              "status": "DONE", "runs": None, "created_at": "2026-11-23", "updated_at": "2026-11-23"}],
                }}
            elif url.endswith("/jobs/job-1/results_link"):
                data = {"data": {"results_link": None if not state["shots"] else "https://test.invalid/result"}}
            elif url == "https://test.invalid/result":
                atoms = Sequence.from_abstract_repr(state["payload"]["sequence_builder"]).register.qubit_ids
                shot_count = state["shots"]
                sample = Results.from_final_bitstrings(tuple(reversed(atoms)), 1000, {
                    "1" + "0" * (len(atoms) - 1): shot_count - 1,
                    "0" * (len(atoms) - 1) + "1": 1,
                })
                data = {"serialised_results": sample.to_abstract_repr()}
            else:
                pytest.fail(f"Unexpected SDK GET: {url}")
        else:
            pytest.fail(f"Unexpected SDK request: {method} {url}")
        response = Response()
        response.status_code = status
        response.url = url
        response._content = json.dumps(data).encode()
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    from qreduce.solving.mwis import pasqal_cloud_submission as submission

    monkeypatch.setattr(submission, "sleep", lambda _: None)
    return state, calls, reference


def _run(monkeypatch, tmp_path, *, explicit_shots=True, budget=0):
    monkeypatch.setattr(sys, "argv", [
        "portfolio_mv", "--output-root", str(tmp_path), "--run-id", "cloud-run",
        "--asset-count", "6", "--graph-edge-mode", "correlation_only", "--correlation-threshold", "0.9",
        "--mis-solver-id", "pasqal_cloud_emulator", "--pasqal-emulator-service", "emu_free",
        "--max-end-to-end-runtime-seconds", str(budget),
        *(["--pasqal-shots", "64"] if explicit_shots else []),
    ])
    return cli.main()


def _recover(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["portfolio_mv", "recover-pasqal", *map(str, args)])
    return cli.main()


def test_automatic_cato_bundle_spans_submission_and_recovery(monkeypatch, tmp_path, cloud):
    import certifi

    state, calls, reference = cloud
    state["check_ca"] = True
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    ca = tmp_path / ".cato" / "cato-ca.pem"
    ca.parent.mkdir()
    ca.write_bytes(Path(certifi.where()).read_bytes())

    assert _run(monkeypatch, tmp_path) == 0
    assert [method for method, _ in calls].count("POST") == 1
    assert reference.is_file()
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    calls.clear()

    assert _recover(monkeypatch, "--reference", reference) == 0
    assert calls and all(method == "GET" for method, _ in calls)
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    assert len(set(state["token_bundles"])) == 2
    assert all(not path.exists() for path in state["token_bundles"])


@pytest.mark.parametrize("explicit_shots", [True, False])
def test_cli_submission_and_recovery(monkeypatch, tmp_path, capsys, cloud, explicit_shots):
    state, calls, reference = cloud
    if not explicit_shots:
        state["shots"] = state["requested_shots"] = 100
    from qreduce.solving.mwis.pasqal_cloud_emulator_backend import (
        PasqalCloudEmulatorMISBackend,
    )

    solve = PasqalCloudEmulatorMISBackend.solve
    results = []

    def observe(self, compiled_job, request):
        assert compiled_job.compiled_problem.graph.edges
        result = solve(self, compiled_job, request)
        results.append(result)
        return result

    monkeypatch.setattr(PasqalCloudEmulatorMISBackend, "solve", observe)
    assert _run(monkeypatch, tmp_path, explicit_shots=explicit_shots) == 0
    assert [m for m, _ in calls].count("POST") == 1
    assert sum(url.endswith("/status") for _, url in calls) == 2
    assert abs((datetime.now(UTC) - datetime.fromisoformat(persistence.load_job_reference(reference).submission_timestamp)).total_seconds()) < 60
    assert "unlabelled-value-123" not in reference.read_text()
    result, = results
    assert result.samples[0].delta == (0, 0, 0, 0, 0, 1)
    assert result.samples[0].occurrence_count == state["shots"] - 1
    capsys.readouterr()
    calls.clear()
    assert _recover(monkeypatch, "--reference", reference) == 0
    decoded = json.loads(capsys.readouterr().out)
    assert decoded["samples"] == [
        {"delta": list(sample.delta), "occurrence_count": sample.occurrence_count} for sample in result.samples
    ]
    assert calls and all(method == "GET" for method, _ in calls)
    assert _recover(monkeypatch, "--batch-id", "batch-1", "--project-id", "fake-project") == 0
    raw = json.loads(capsys.readouterr().out)
    assert raw["counts"] and raw["atom_order"] and not raw["node_order"] and not raw["samples"]
    calls.clear()
    monkeypatch.setenv("PASQAL_PROJECT_ID", "other-project")
    assert _recover(monkeypatch, "--reference", reference) == 1
    assert not calls


@pytest.mark.parametrize("http_status,diagnostic", [(503, "submission_outcome_unknown"), (307, "submission_outcome_unknown"),
                                                   ("timeout", "submission_outcome_unknown"), (403, "submission_rejected")])
def test_create_is_never_retried(monkeypatch, tmp_path, cloud, http_status, diagnostic):
    state, calls, reference = cloud
    state["post"] = http_status
    assert _run(monkeypatch, tmp_path) == 0
    assert [m for m, _ in calls] == ["POST"]
    assert not reference.exists()
    report = (tmp_path / "cloud-run" / "run_result.json").read_text()
    assert diagnostic in report and "unlabelled-value-123" not in report


@pytest.mark.parametrize("shots", [0, 63])
def test_done_batch_without_all_results_is_not_success(monkeypatch, tmp_path, capsys, cloud, shots):
    state, calls, reference = cloud
    state["shots"] = shots
    assert _run(monkeypatch, tmp_path) == 0
    assert reference.is_file()
    assert "read_results" in (tmp_path / "cloud-run" / "run_result.json").read_text()
    calls.clear()
    assert _recover(monkeypatch, "--reference", reference) == 1
    assert "Batch ID: batch-1" in capsys.readouterr().err
    assert calls and all(method == "GET" for method, _ in calls)


def test_persistence_failure_leaves_batch_id_but_does_not_poll(monkeypatch, tmp_path, cloud):
    _, calls, reference = cloud

    def fail(*args):
        raise OSError("unlabelled-value-123")

    monkeypatch.setattr(persistence, "save_job_reference", fail)
    assert _run(monkeypatch, tmp_path) == 0
    assert [method for method, _ in calls] == ["POST"]
    assert not reference.exists()
    report = (tmp_path / "cloud-run" / "run_result.json").read_text()
    assert "batch-1" in report and "persistence_failed" in report
    assert "unlabelled-value-123" not in report


def test_timeout_after_id_preserves_reference_without_polling(monkeypatch, tmp_path, cloud):
    from qreduce.solving.mwis import pasqal_cloud_emulator_backend as backend
    from qreduce.solving.mwis import pasqal_cloud_submission as submission

    state, calls, reference = cloud
    state.update(clock=0, expire_after_post=True)
    monkeypatch.setattr(backend, "perf_counter", lambda: state["clock"])
    monkeypatch.setattr(submission, "perf_counter", lambda: state["clock"])
    assert _run(monkeypatch, tmp_path, budget=30) == 0
    assert [method for method, _ in calls] == ["POST"]
    assert reference.exists()
    report = (tmp_path / "cloud-run" / "run_result.json").read_text()
    assert "batch-1" in report and "Local deadline expired" in report


def test_remote_terminal_and_access_error_are_not_local_timeouts(monkeypatch, tmp_path, cloud):
    state, calls, reference = cloud
    state["status"] = ["TIMED_OUT"]
    assert _run(monkeypatch, tmp_path) == 0
    assert [method for method, _ in calls] == ["POST", "GET"]
    report = (tmp_path / "cloud-run" / "run_result.json").read_text()
    assert "TIMED_OUT" in report and "Local deadline expired" not in report
    state["access_denied"] = True
    calls.clear()
    assert _recover(monkeypatch, "--reference", reference) == 1
    assert [method for method, _ in calls] == ["GET"]