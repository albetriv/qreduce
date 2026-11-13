"""Runner that persists complete repository experiments for later notebook analysis."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal

from qreduce.artifacts.metadata import (
    pretty_json,
    redact_metadata,
    sha256_hex,
    to_primitive,
    utc_created_at,
)
from qreduce.domains import ReducibleProblemAdapter
from qreduce.experiments.artifacts import ARTIFACT_SCHEMA_VERSION
from qreduce.models import ResolvedRunConfig
from qreduce.pipeline import (
    MultiRoundRunResult,
    SinglePassRunResult,
    run_multi_round,
    run_single_pass,
)
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.residual import ClassicalSolverRegistry


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """One completed repository experiment, including its published artifact directory."""

    experiment_id: str
    run_directory: Path
    result: SinglePassRunResult | MultiRoundRunResult


def run_experiment(
    experiment_id: str,
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mode: Literal["single_pass", "multi_round"] = "single_pass",
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    output_root: str | Path = "outputs",
    experiment_metadata: Mapping[str, object] | None = None,
) -> ExperimentRun:
    """Run QReduce once and persist a complete artifact directory for notebook loading.

    A normalized QReduce failure is still a completed experiment and is persisted.
    A serialization or publication error raises and leaves no final run directory.

    Args:
        mode: "single_pass" for single reduction round, "multi_round" for iterative.
    """

    _require_identifier(experiment_id, "experiment_id")
    run_id = config.run_identity.run_id
    _require_identifier(run_id, "config.run_identity.run_id")
    destination = Path(output_root) / experiment_id / run_id
    if destination.exists():
        raise FileExistsError(
            f"Experiment artifact directory already exists: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(mkdtemp(prefix=f".{run_id}.", dir=destination.parent))
    external_staging = None
    external_published = None
    try:
        export_path = None
        write_path = None
        if config.classical_solve.model_export_enabled:
            requested = config.classical_solve.model_export_path
            if requested is not None and (not isinstance(requested, str) or not requested.strip()):
                raise ValueError("Model export path must be non-blank.")
            export_path = Path(requested).resolve() if requested is not None else (
                destination.resolve() / "residual_model.lp"
            )
            if export_path.suffix.lower() not in {".lp", ".mps"}:
                raise ValueError("Model export requires an .lp or .mps file path.")
            if export_path.parent == destination.resolve():
                write_path = temporary_root / export_path.name
            else:
                if export_path.is_relative_to(destination.resolve()):
                    raise ValueError("Model export must be directly inside the run directory.")
                if export_path.exists():
                    raise FileExistsError(f"Model export already exists: {export_path}")
                external_staging = Path(mkdtemp(prefix=".qreduce-export.", dir=export_path.parent))
                write_path = external_staging / export_path.name
            config = replace(config, classical_solve=replace(
                config.classical_solve, model_export_path=str(export_path)
            ))

        # Execute pipeline based on mode
        if mode == "multi_round":
            result: SinglePassRunResult | MultiRoundRunResult = run_multi_round(
                problem,
                adapter,
                config,
                mis_solver_registry=mis_solver_registry,
                classical_solver_registry=classical_solver_registry,
            )
            exported = None  # Multi-round doesn't support model export yet
        else:
            result = run_single_pass(
                problem,
                adapter,
                config,
                mis_solver_registry=mis_solver_registry,
                classical_solver_registry=classical_solver_registry,
                _model_export_write_path=str(write_path) if write_path else None,
            )
            exported = write_path if write_path and write_path.is_file() else None
            if exported and result.classical_result and not result.classical_result.model_export_path:
                result = replace(result, classical_result=replace(
                    result.classical_result, model_export_path=str(export_path)
                ))

        _write_artifacts(
            temporary_root,
            experiment_id,
            problem,
            result,
            experiment_metadata or {},
            exported,
            export_path,
            external_staging is not None,
            mode,
        )
        if exported and external_staging is not None:
            os.link(exported, export_path)
            external_published = export_path
        os.replace(temporary_root, destination)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        if external_published is not None:
            external_published.unlink(missing_ok=True)
        raise
    finally:
        if external_staging is not None:
            shutil.rmtree(external_staging, ignore_errors=True)
    return ExperimentRun(
        experiment_id=experiment_id, run_directory=destination, result=result
    )


def _write_artifacts(
    directory: Path,
    experiment_id: str,
    problem: object,
    result: SinglePassRunResult | MultiRoundRunResult,
    experiment_metadata: Mapping[str, object],
    exported: Path | None,
    export_path: Path | None,
    external_export: bool,
    mode: str,
) -> None:
    config = result.resolved_config.to_dict()
    problem_data = redact_metadata(to_primitive(problem))
    result_data = result.to_dict()
    files: dict[str, object] = {
        "config_used.json": config,
        "experiment_metadata.json": redact_metadata(to_primitive(experiment_metadata)),
        "problem.json": problem_data,
        "run_result.json": result_data,
    }

    # For multi-round, also write per-round results
    if isinstance(result, MultiRoundRunResult) and result.round_results:
        for i, round_result in enumerate(result.round_results):
            files[f"round_{i:02d}_result.json"] = round_result.to_dict()
        if result.recovery_attempts:
            files["recovery_attempts.json"] = [
                {
                    "attempt_index": a.attempt_index,
                    "trigger_reason": a.trigger_reason.value if a.trigger_reason else None,
                    "expanded_domain_size": a.expanded_domain_size,
                    "previous_domain_size": a.previous_domain_size,
                    "outcome": a.outcome,
                }
                for a in result.recovery_attempts
            ]

    # Single-pass specific: canonical MWIS problem
    if isinstance(result, SinglePassRunResult):
        compilation = result.mis_compilation_result
        if compilation is not None and compilation.compiled_job is not None:
            files["canonical_mwis_problem.json"] = (
                compilation.compiled_job.compiled_problem.to_dict()
            )

    content_hashes: dict[str, str] = {}
    for filename, contents in files.items():
        _write_json(directory / filename, contents)
        content_hashes[filename] = sha256_hex(contents)

    model_export = None
    if exported is not None and export_path is not None:
        digest = sha256(exported.read_bytes()).hexdigest()
        model_export = {
            "path": str(export_path), "format": export_path.suffix[1:].lower(),
            "sha256": digest, "external": external_export,
        }
        if not external_export:
            content_hashes[export_path.name] = digest

    manifest: dict[str, object] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "producer_version": _producer_version(),
        "created_at": utc_created_at(),
        "experiment_id": experiment_id,
        "run_id": result.run_result.run_id,
        "run_status": result.run_result.run_status.value,
        "run_mode": mode,
        "config_hash": result.run_result.config_hash,
        "policy_provenance": config["policy_provenance"],
        "files": content_hashes,
        "model_export": model_export,
    }

    # Multi-round specific manifest fields
    if isinstance(result, MultiRoundRunResult):
        manifest["round_count"] = len(result.round_results)
        manifest["recovery_attempt_count"] = len(result.recovery_attempts)

    _write_json(directory / "run_manifest.json", manifest)


def _write_json(path: Path, contents: object) -> None:
    """Write readable JSON while content hashes use compact canonical JSON."""

    path.write_text(pretty_json(contents) + "\n", encoding="utf-8")


def _producer_version() -> str:
    from qreduce import __version__

    return __version__


def _require_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or Path(value).name != value:
        raise ValueError(f"{field} must be a non-blank path component.")
