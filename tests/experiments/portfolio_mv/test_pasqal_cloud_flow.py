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
        target = state.get("device_type", "EMU_FREE")
        if method == "GET" and url.endswith("/devices/specs") and "device_specs" in state:
            data = {"data": {target: state["device_specs"]}}
        elif method == "POST" and url.endswith("/api/v1/batches"):
            assert adapter.max_retries.total == 0
            assert journal.is_dir() and not reference.exists()
            state["payload"] = payload = json.loads(request.body)
            assert payload["device_type"] == target and payload["open"] is False
            assert payload["project_id"] == "fake-project"
            shots = state.get("requested_shots", 64)
            if target == "EMU_FREE":
                assert payload["jobs"] == [{}]
                assert json.loads(payload["backend_configuration"])["default_num_shots"] == shots
            else:
                assert payload["jobs"] == [{"runs": shots}]
                assert "backend_configuration" not in payload
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
                    "device_type": state.get("reported_device_type", target), "status": "DONE", "open": False, "complete": True,
                    "created_at": "2026-11-23", "updated_at": "2026-11-23",
                    "sequence_builder": state["payload"]["sequence_builder"],
                    "jobs": [{"id": "job-1", "batch_id": "batch-1", "project_id": "fake-project",
                              "status": "DONE", "runs": state["payload"]["jobs"][0].get("runs"),
                              "created_at": "2026-11-23", "updated_at": "2026-11-23"}],
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


@pytest.fixture
def qpu_cloud(cloud):
    from dataclasses import replace

    from pulser.devices import AnalogDevice
    from pulser.register import RegisterLayout

    state, _, _ = cloud
    layout = RegisterLayout([
        (0.27, -7.21), (-6.45, -2.64), (4.77, 14.78),
        (0.53, -18.97), (14.06, -0.83), (-13.17, 14.87),
        (-24, 0), (-24, 8), (-24, -8), (24, 0), (24, 8), (24, -8),
    ], slug="test-layout")
    device = replace(AnalogDevice, name="FRESNEL_CAN1", pre_calibrated_layouts=(layout,))
    state.update(device_type="FRESNEL_CAN1", device_specs=device.to_abstract_repr())
    return cloud


def _run_qpu(monkeypatch, tmp_path, *, consent=True):
    monkeypatch.setattr(sys, "argv", [
        "portfolio_mv", "--output-root", str(tmp_path), "--run-id", "cloud-run",
        "--asset-count", "6", "--graph-edge-mode", "correlation_only", "--correlation-threshold", "0.9",
        "--mis-solver-id", "pasqal_qpu", "--pasqal-device-id", "FRESNEL_CAN1",
        "--pasqal-shots", "64", *(["--pasqal-cost-consent"] if consent else []),
    ])
    return cli.main()


def test_qpu_preflight_submit_poll_and_recover(monkeypatch, tmp_path, capsys, qpu_cloud):
    state, calls, reference = qpu_cloud
    assert cli._preflight_main(["--discover"]) == 0
    discovered = json.loads(capsys.readouterr().out)["devices"][0]
    assert discovered["available_layouts"] == ["test-layout"]
    assert discovered["accepts_new_layouts"] is True
    assert cli._preflight_main([
        "--compile", "--device-id", "FRESNEL_CAN1", "--asset-count", "6",
        "--graph-edge-mode", "correlation_only", "--correlation-threshold", "0.9",
    ]) == 0
    preflight = json.loads(capsys.readouterr().out)
    assert preflight["success"] and not preflight["presolve_applied"] and preflight["edge_count"] > 0
    assert preflight["outcome"] == "qpu_sequence_validated"
    assert preflight["mapping_result"]["outcome"] == "found"
    assert preflight["mapping_diagnostic"]["extra_edges"] == []
    assert calls and all(method == "GET" and url.endswith("/devices/specs") for method, url in calls)

    with pytest.raises(SystemExit) as error:
        _run_qpu(monkeypatch, tmp_path, consent=False)
    assert error.value.code == 2
    assert all(method != "POST" for method, _ in calls)
    capsys.readouterr()
    assert _run_qpu(monkeypatch, tmp_path) == 0
    assert sum(method == "POST" for method, _ in calls) == 1
    record = persistence.load_job_reference(reference)
    assert record.target_type == "qpu" and record.device_id == state["device_type"]
    result = json.loads((tmp_path / "cloud-run" / "round_00_result.json").read_text())
    assert result["mis_execution_result"]["completion_status"] == "completed"
    assert result["mis_compilation_result"]["compiled_job"]["provider_payload"]["mapping"]["valid"]
    assert state["payload"]["sequence_builder"] == (
        result["mis_compilation_result"]["compiled_job"]["provider_payload"]["sequence_abstract_repr"]
    )
    capsys.readouterr()
    calls.clear()
    assert _recover(monkeypatch, "--reference", reference) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["shots_received"] == 64
    assert recovered["samples"][0] == {"delta": [0, 0, 0, 0, 0, 1], "occurrence_count": 63}
    assert calls and all(method == "GET" for method, _ in calls)
    calls.clear()
    state["reported_device_type"] = "FRESNEL"
    assert _recover(monkeypatch, "--reference", reference) == 1
    assert calls and all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("block", ["consent", "specifications"])
def test_qpu_backend_blocks_creation_before_post(monkeypatch, tmp_path, qpu_cloud, block):
    from dataclasses import replace

    from pulser import Sequence

    from qreduce.solving.mwis.pasqal_qpu_backend import PasqalQPUMISBackend

    state, calls, reference = qpu_cloud
    solve = PasqalQPUMISBackend.solve

    def change_before_solve(self, compiled_job, request):
        if block == "consent":
            request = replace(request, execution_parameters={"shots": 64})
        else:
            seq = Sequence.from_abstract_repr(compiled_job.provider_payload["sequence_abstract_repr"])
            state["device_specs"] = replace(seq.device, max_runs=1999).to_abstract_repr()
        return solve(self, compiled_job, request)

    monkeypatch.setattr(PasqalQPUMISBackend, "solve", change_before_solve)
    assert _run_qpu(monkeypatch, tmp_path) == 0
    assert calls and all(method == "GET" and url.endswith("/devices/specs") for method, url in calls)
    assert not reference.exists()
    result = json.loads((tmp_path / "cloud-run" / "round_00_result.json").read_text())
    assert block in result["mis_execution_result"]["diagnostic_message"].lower()


@pytest.mark.parametrize(("response", "expected"), [
    (403, "submission_rejected"), (500, "submission_outcome_unknown"),
    ("timeout", "submission_outcome_unknown"),
])
def test_qpu_create_is_not_retried(monkeypatch, tmp_path, qpu_cloud, response, expected):
    state, calls, reference = qpu_cloud
    state["post"] = response
    assert _run_qpu(monkeypatch, tmp_path) == 0
    assert sum(method == "POST" for method, _ in calls) == 1
    assert not reference.exists()
    assert not any(url.endswith("/status") for _, url in calls)
    result = json.loads((tmp_path / "cloud-run" / "round_00_result.json").read_text())
    execution = result["mis_execution_result"]
    assert execution["effective_execution_parameters"]["status"] == expected
    if expected == "submission_outcome_unknown":
        assert "Reconcile with Pasqal" in execution["diagnostic_message"]
    assert "unlabelled-value-123" not in execution["diagnostic_message"]


@pytest.mark.parametrize("failed_pair", ["edge_in_margin", "extra_edge"])
def test_qpu_preflight_rejects_invalid_final_traps(qpu_cloud, capsys, failed_pair):
    from dataclasses import replace

    from pulser.devices import AnalogDevice
    from pulser.register import RegisterLayout

    state, calls, _ = qpu_cloud
    # Create a layout with EXACTLY 6 traps so the mapper has no alternatives
    points = [(0.27, -7.21), (-6.45, -2.64), (4.77, 14.78),
              (0.53, -18.97), (14.06, -0.83), (-13.17, 14.87)]
    if failed_pair == "edge_in_margin":
        points[1] = (-8.0, -2.64)
    else:
        points[3] = (0.53, -16.7)
    # No extra points - mapper must use all 6 and will hit the geometric violation
    layout = RegisterLayout(points, slug="invalid-for-graph")
    device = replace(AnalogDevice, name="FRESNEL_CAN1", pre_calibrated_layouts=(layout,), max_layout_filling=1.0)
    state["device_specs"] = device.to_abstract_repr()
    assert cli._preflight_main([
        "--compile", "--device-id", "FRESNEL_CAN1",
        "--graph-edge-mode", "correlation_only", "--correlation-threshold", "0.9",
    ]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["terminal_reason"] == "mis_device_mapping_failed"
    assert result["mapping_result"]["outcome"] == "exhausted"
    assert calls and all(method == "GET" and url.endswith("/devices/specs") for method, url in calls)


@pytest.mark.parametrize(("layout_mode", "submission"), [
    ("calibrated", "success"), ("custom", "success"), ("custom", "timeout"),
    ("custom", "specifications"), ("custom", "project"),
])
def test_qpu_preflight_from_round_artifact_preserves_problem(
    monkeypatch, tmp_path, capsys, qpu_cloud, layout_mode, submission,
):
    from hashlib import sha256

    from pulser import Sequence

    from qreduce.artifacts.metadata import sha256_hex, to_primitive
    from qreduce.experiments.portfolio_mv.inputs import build_synthetic_portfolio_inputs, default_graph_policy
    from qreduce.pipeline.single_pass import build_canonical_mwis_problem
    from qreduce.solving.mwis.pasqal_qpu_backend import PasqalQPUMISBackend

    policy = default_graph_policy(edge_mode="correlation_only", correlation_threshold=0.9)
    inputs = build_synthetic_portfolio_inputs("artifact-example", asset_count=6, graph_policy=policy)
    expected = build_canonical_mwis_problem(inputs.problem, inputs.adapter, inputs.config)
    files = {
        "config_used.json": {}, "experiment_metadata.json": {}, "problem.json": {}, "run_result.json": {},
        "round_00_result.json": {"round_index": 0, "mis_compilation_result": {"compiled_job": {
            "compiled_problem": to_primitive(expected),
        }}},
    }
    files["run_manifest.json"] = {
        "artifact_schema_version": "1.1", "experiment_id": "synthetic-portfolio",
        "run_id": "artifact-example", "created_at": "2026-01-01T00:00:00Z",
        "files": {name: sha256_hex(data) for name, data in files.items()},
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")

    compile_problem = PasqalQPUMISBackend.compile

    def verify_compile(backend, problem, request):
        assert to_primitive(problem) == to_primitive(expected)
        assert request.node_order == expected.graph.node_ids
        assert request.residual_time_budget_seconds == 30
        return compile_problem(backend, problem, request)

    monkeypatch.setattr(PasqalQPUMISBackend, "compile", verify_compile)
    export_path = tmp_path / "sequence.json"
    args = ["--from-artifacts", str(tmp_path), "--device-id", "FRESNEL_CAN1",
            "--compilation-time-limit-seconds", "30", "--layout-mode", layout_mode,
            "--sequence-output", str(export_path)]
    assert cli._preflight_main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["original_run_id"] == "artifact-example"
    assert result["outcome"] == "qpu_sequence_validated"
    assert result["mapping_diagnostic"]["valid"]
    assert result["layout_mode"] == layout_mode
    assert result["sequence_sha256"] == sha256(export_path.read_bytes()).hexdigest()
    exported = Sequence.from_abstract_repr(export_path.read_text(encoding="utf-8"))
    assert exported.is_measured()
    if layout_mode == "custom":
        assert result["layout_id"] == f"custom:{result['layout_sha256']}"
        assert result["mapping_result"]["trap_count"] == exported.register.layout.number_of_traps
    state, calls, reference = qpu_cloud
    assert calls and all(method == "GET" for method, _ in calls)

    calls.clear()
    report_path = tmp_path / "preflight.json"
    report_path.write_text(json.dumps(result), encoding="utf-8")
    submit_args = ["portfolio_mv", "submit-preflight", "--preflight-report", str(report_path),
                   "--sequence", str(export_path), "--from-artifacts", str(tmp_path),
                   "--device-id", "FRESNEL_CAN1", "--run-id", "cloud-run", "--shots", "64",
                   "--output-root", str(tmp_path)]

    def no_compilation(*args, **kwargs):
        pytest.fail("Submission must not compile")

    with monkeypatch.context() as patch:
        patch.setattr(PasqalQPUMISBackend, "compile", no_compilation)
        patch.setattr(sys, "argv", submit_args)
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 2 and not calls
        capsys.readouterr()

        patch.setattr(sys, "argv", submit_args + ["--check-only"])
        assert cli.main() == 0
        assert json.loads(capsys.readouterr().out)["outcome"] == "local_check_passed"
        assert not calls and not reference.parent.exists()

        patch.setattr(sys, "argv", submit_args + ["--pasqal-cost-consent"])
        pristine = export_path.read_bytes()
        export_path.write_bytes(pristine + b"\n")
        assert cli.main() == 1
        assert "sequence hash mismatch" in capsys.readouterr().err.lower()
        assert not calls and not reference.parent.exists()
        export_path.write_bytes(pristine)

        if submission == "timeout":
            state["post"] = "timeout"
        elif submission == "specifications":
            from dataclasses import replace

            state["device_specs"] = replace(exported.device, max_runs=1001).to_abstract_repr()
        elif submission == "project":
            patch.setenv("PASQAL_PROJECT_ID", "other-project")
        assert cli.main() == (0 if submission == "success" else 1)
        execution = json.loads(capsys.readouterr().out)["result"]
        assert (reference.parent / "submission_intent.json").is_file()
        assert sum(method == "POST" for method, _ in calls) == int(submission in ("success", "timeout"))
        if submission == "success":
            assert reference.is_file()
            assert state["payload"]["sequence_builder"].encode() == pristine
        elif submission == "timeout":
            assert not reference.exists()
            assert execution["effective_execution_parameters"]["status"] == "submission_outcome_unknown"
        else:
            assert submission in execution["diagnostic_message"].lower()
        calls.clear()
        assert cli.main() == 1
        assert "already reserved" in capsys.readouterr().err and not calls

    (tmp_path / "round_00_result.json").write_text("{}", encoding="utf-8")
    assert cli._preflight_main(args) == 1
    assert "hash mismatch" in capsys.readouterr().err.lower()
    assert not calls


@pytest.mark.parametrize("allows_custom", [True, False])
def test_qpu_custom_preflight_with_no_calibrated_layouts(capsys, qpu_cloud, allows_custom):
    from dataclasses import replace

    from pulser.devices import Device

    state, calls, _ = qpu_cloud
    device = Device.from_abstract_repr(state["device_specs"])
    state["device_specs"] = replace(device, pre_calibrated_layouts=(), accepts_new_layouts=allows_custom,
                                     requires_layout=True).to_abstract_repr()
    assert cli._preflight_main(["--compile", "--device-id", "FRESNEL_CAN1", "--layout-mode", "custom",
                                "--graph-edge-mode", "correlation_only"]) == (0 if allows_custom else 1)
    result = json.loads(capsys.readouterr().out)
    assert result["mapping_result"]["outcome"] == ("found" if allows_custom else "custom_layout_not_supported")
    assert calls and all(method == "GET" for method, _ in calls)


def test_qpu_preflight_continues_in_same_layout_after_register_rejection(monkeypatch, capsys, qpu_cloud):
    from pulser.devices import Device

    original = Device.validate_register
    seen = []

    def reject_first(device, register):
        seen.append(tuple(tuple(float(x) for x in point) for point in register.qubits.values()))
        if len(seen) == 1:
            raise ValueError("synthetic candidate rejection")
        return original(device, register)

    monkeypatch.setattr(Device, "validate_register", reject_first)
    assert cli._preflight_main(["--compile", "--device-id", "FRESNEL_CAN1",
                                "--graph-edge-mode", "correlation_only"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mapping_result"]["rejected_candidates_by_layout"] == {"test-layout": 1}
    assert seen[0] != seen[1]
    _, calls, _ = qpu_cloud
    assert calls and all(method == "GET" for method, _ in calls)


def test_qpu_preflight_pulse_error_is_not_mapping_failure(monkeypatch, capsys, qpu_cloud):
    from qreduce.solving.mwis import pulse_strategy

    def invalid_sequence(*_args):
        raise ValueError("invalid pulse")

    monkeypatch.setattr(pulse_strategy, "build_pulse_sequence", invalid_sequence)
    assert cli._preflight_main(["--compile", "--device-id", "FRESNEL_CAN1",
                                "--graph-edge-mode", "correlation_only"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["terminal_reason"] == "mis_compilation_failed"
    assert result["mapping_result"]["outcome"] == "sequence_invalid"
    _, calls, _ = qpu_cloud
    assert calls and all(method == "GET" for method, _ in calls)


def test_qpu_preflight_skips_layout_with_incompatible_filling(capsys, qpu_cloud):
    from dataclasses import replace

    from pulser.devices import Device
    from pulser.register import RegisterLayout

    state, calls, _ = qpu_cloud
    device = Device.from_abstract_repr(state["device_specs"])
    too_small = RegisterLayout([(8 * (i % 3), 8 * (i // 3)) for i in range(6)], slug="a-small")
    state["device_specs"] = replace(
        device, pre_calibrated_layouts=(too_small, *device.calibrated_register_layouts.values()),
    ).to_abstract_repr()
    assert cli._preflight_main(["--compile", "--device-id", "FRESNEL_CAN1",
                                "--graph-edge-mode", "correlation_only"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["layout_id"] == "test-layout"
    assert result["mapping_result"]["rejected_layouts"] == [
        {"layout_id": "a-small", "reason": "MaxQubitNumberError"},
    ]
    assert calls and all(method == "GET" for method, _ in calls)


def test_qpu_preflight_reports_compilation_deadline(monkeypatch, capsys, qpu_cloud):
    from qreduce.solving.mwis import pasqal_qpu_backend

    ticks = iter((0.0, 2.0, 2.0))
    monkeypatch.setattr(pasqal_qpu_backend, "perf_counter", lambda: next(ticks))
    assert cli._preflight_main(["--compile", "--device-id", "FRESNEL_CAN1",
                                "--graph-edge-mode", "correlation_only",
                                "--compilation-time-limit-seconds", "1"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["mapping_result"]["outcome"] == "timeout"
    assert not result["qpu_sequence_validated"]
    _, calls, _ = qpu_cloud
    assert all(method == "GET" for method, _ in calls)


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