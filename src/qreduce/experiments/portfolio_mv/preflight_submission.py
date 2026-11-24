"""Execute an exact, previously validated QPU sequence without compiling again."""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from qreduce.artifacts.metadata import sha256_hex
from qreduce.config import validate_timeout_value
from qreduce.experiments.artifacts import ExperimentArtifactError
from qreduce.experiments.portfolio_mv.preflight_artifacts import load_preflight_problem
from qreduce.solving.mwis.audit import WeightEncodingMode
from qreduce.solving.mwis.contracts import CompiledMISJob, MISBackendRequest, MISCompletionStatus
from qreduce.solving.mwis.pasqal_cloud_persistence import reserve_qpu_submission
from qreduce.solving.mwis.pasqal_mapping import diagnose_layout
from qreduce.solving.mwis.pasqal_qpu_backend import (
    QPU_MARGIN_UM,
    QPU_PAYLOAD_VERSION,
    QPU_RADIUS_UM,
    PasqalQPUMISBackend,
)
from qreduce.status import BackendFamily, ExecutionMode, ProblemForm


def load_saved_qpu_job(args, backend: PasqalQPUMISBackend) -> CompiledMISJob:
    """Recheck the artifact, device and atom order; preserve the sequence bytes."""
    from pulser import Sequence
    from pulser.devices import Device

    report = json.loads(args.preflight_report.read_bytes())
    if (not isinstance(report, dict) or report.get("source") != "artifacts"
            or report.get("outcome") != "qpu_sequence_validated"
            or report.get("qpu_sequence_validated") is not True
            or report.get("presolve_applied") is not False
            or report.get("device_id") != args.device_id or args.device_id.startswith("EMU_")):
        raise ValueError("A validated, artifact-based QPU report for the requested device is required.")

    sequence_bytes = args.sequence.read_bytes()
    digest = sha256(sequence_bytes).hexdigest()
    if digest != report.get("sequence_sha256"):
        raise ValueError("Saved sequence hash mismatch.")
    original_run_id, problem = load_preflight_problem(args.from_artifacts)
    graph = problem.graph
    if not args.check_only and (
        not isinstance(report.get("project_id_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", report["project_id_sha256"])
        or "problem_sha256" not in report
    ):
        raise ValueError("Paid submission requires a preflight report with project and problem hashes.")
    if (original_run_id != report.get("original_run_id")
            or sha256(graph.to_canonical_json().encode()).hexdigest() != report.get("graph_hash")
            or ("problem_sha256" in report and sha256_hex(problem) != report["problem_sha256"])):
        raise ValueError("Saved report does not match the canonical problem.")

    sequence_repr = sequence_bytes.decode("utf-8")
    seq = Sequence.from_abstract_repr(sequence_repr)
    device = seq.device
    if not isinstance(device, Device):
        raise ValueError("The saved sequence was not compiled for a physical device.")
    device_digest = sha256(device.to_abstract_repr().encode()).hexdigest()
    if device_digest != report.get("device_spec_sha256"):
        raise ValueError("Saved sequence device specifications do not match the report.")
    if not seq.is_measured() or seq.is_parametrized() or seq.is_register_mappable():
        raise ValueError("The saved sequence must be measured, concrete and non-mappable.")
    register = seq.register
    atom_order = tuple(f"q{i}" for i in range(len(graph.node_ids)))
    layout = register.layout
    if layout is None or tuple(register.qubit_ids) != atom_order:
        raise ValueError("Saved sequence has no layout or its atom order does not match the graph.")
    device.validate_layout(layout)
    device.validate_layout_filling(register)
    device.validate_register(register)
    layout_mode = report.get("layout_mode")
    layout_id = report.get("layout_id")
    if layout_mode == "custom":
        layout_digest = sha256_hex(layout.coords.tolist())
        if (not device.accepts_new_layouts or layout_digest != report.get("layout_sha256")
                or layout_id != f"custom:{layout_digest}"):
            raise ValueError("Saved custom layout does not match the report or device.")
    elif layout_mode != "calibrated" or device.calibrated_register_layouts.get(layout_id) != layout:
        raise ValueError("Saved calibrated layout does not match the report or device.")
    coordinates = {node: tuple(map(float, register.qubits[atom]))
                   for node, atom in zip(graph.node_ids, atom_order, strict=True)}
    trap_ids = layout.get_traps_from_coordinates(*register.qubits.values())
    mapping = report.get("mapping_result")
    if (not isinstance(mapping, dict) or mapping.get("outcome") != "found"
            or mapping.get("assignment") != dict(zip(graph.node_ids, trap_ids, strict=True))
            or not diagnose_layout(graph, coordinates, QPU_RADIUS_UM, QPU_MARGIN_UM)["valid"]):
        raise ValueError("Saved atom-to-node mapping does not match the report or graph geometry.")
    if device.max_runs is not None and args.shots > device.max_runs:
        raise ValueError(f"Requested shots exceed the saved device limit ({device.max_runs}).")

    return CompiledMISJob(
        compiled_job_id=f"{args.run_id}:round:0:pasqal-qpu", run_id=args.run_id,
        round_index=0, node_order=graph.node_ids, problem_form=ProblemForm.MIS_GRAPH,
        compiled_problem=problem, requested_provider_id="pasqal", requested_backend_id="pasqal_qpu",
        effective_provider_id="pasqal", effective_backend_id="pasqal_qpu",
        backend_family=BackendFamily.NEUTRAL_ATOM, execution_mode=ExecutionMode.REMOTE,
        effective_device_id=f"qpu:{args.device_id}", runtime_seconds=0.0,
        effective_compilation_parameters={"layout_mode": layout_mode, "pasqal_profile": args.profile},
        capabilities_snapshot=backend.capabilities(), provider_payload_type="pasqal.qpu.sequence",
        provider_payload_version=QPU_PAYLOAD_VERSION,
        provider_payload={
            "target": "qpu", "presolve_applied": False, "node_order": list(graph.node_ids),
            "device_id": args.device_id, "layout_mode": layout_mode,
            "device_max_runs": device.max_runs, "device_spec_sha256": device_digest,
            "sequence_abstract_repr": sequence_repr, "sequence_sha256": digest,
            "pasqal_profile": args.profile, "project_id_sha256": report.get("project_id_sha256"),
            "weight_encoding_mode": WeightEncodingMode.CLASSICAL_RANKING.value,
        },
    )


def submit_preflight_main(argv: list[str], *, default_output_root: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-report", required=True, type=Path)
    parser.add_argument("--sequence", required=True, type=Path)
    parser.add_argument("--from-artifacts", required=True, type=Path)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--shots", type=int, required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--output-root", type=Path, default=default_output_root)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true", help="Validate locally, without cloud access.")
    mode.add_argument("--pasqal-cost-consent", action="store_true", help="Authorize one paid QPU submission.")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id) or args.shots < 1:
        parser.error("Use a safe run ID and a positive shot count.")
    error = validate_timeout_value(args.timeout_seconds, "--timeout-seconds")
    if error:
        parser.error(error)

    journal = args.output_root / ".pasqal-cloud-jobs" / args.run_id
    backend = PasqalQPUMISBackend(job_reference_directory=journal)
    try:
        job = load_saved_qpu_job(args, backend)
        summary = {"run_id": args.run_id, "device_id": args.device_id, "shots": args.shots,
                   "sequence_sha256": job.provider_payload["sequence_sha256"]}
        if args.check_only:
            print(json.dumps({**summary, "outcome": "local_check_passed"}))
            return 0
        if (args.output_root / args.run_id).exists():
            raise ValueError("Run ID already exists; do not reuse a previous run ID.")
        request = MISBackendRequest(
            run_id=args.run_id, round_index=0, compiled_job_id=job.compiled_job_id,
            node_order=job.node_order, random_seed=None, requested_solution_count=1,
            residual_time_budget_seconds=args.timeout_seconds,
            execution_parameters={"shots": args.shots, "_cost_consent": args.pasqal_cost_consent},
        )
        reserve_qpu_submission(journal, {**summary, "profile": args.profile,
                                        "reserved_at": datetime.now(UTC).isoformat()})
        result = backend.solve(job, request)
        outcome = {**summary, "journal": str(journal.resolve()), "result": result.to_dict()}
        text = json.dumps(outcome, indent=2)
        print(text)
        (journal / "submission_result.json").write_text(text + "\n", encoding="utf-8")
        return 0 if result.completion_status == MISCompletionStatus.COMPLETED else 1
    except FileExistsError:
        print("Error: Run ID already reserved. Reconcile the existing attempt; do not resubmit.", file=sys.stderr)
    except (ExperimentArtifactError, OSError, TypeError, ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
    return 1