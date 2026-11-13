"""Runner that persists complete repository experiments for later notebook analysis."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp

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
from qreduce.pipeline import PipelineRunResult, run_pipeline
from qreduce.solving.mwis import MISSolverRegistry
from qreduce.solving.residual import ClassicalSolverRegistry


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """One completed repository experiment, including its published artifact directory."""

    experiment_id: str
    run_directory: Path
    result: PipelineRunResult


def run_experiment(
    experiment_id: str,
    problem: object,
    adapter: ReducibleProblemAdapter,
    config: ResolvedRunConfig,
    *,
    mis_solver_registry: MISSolverRegistry | None = None,
    classical_solver_registry: ClassicalSolverRegistry | None = None,
    output_root: str | Path = "outputs",
    experiment_metadata: Mapping[str, object] | None = None,
) -> ExperimentRun:
    """Run QReduce once and persist a complete artifact directory for notebook loading.

    A normalized QReduce failure is still a completed experiment and is persisted.
    A serialization or publication error raises and leaves no final run directory.

    Behavior is determined by config.reduction.max_reduction_rounds:
    - 0: Classical-only baseline (no MIS, no reduction)
    - 1: Single reduction round
    - >1: Iterative reduction with optional recovery
    """

    _require_identifier(experiment_id, "experiment_id")
    run_id = config.run_identity.run_id
    _require_identifier(run_id, "config.run_identity.run_id")
    destination = Path(output_root) / run_id
    if destination.exists():
        raise FileExistsError(
            f"Experiment artifact directory already exists: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(mkdtemp(prefix=f".{run_id}.", dir=destination.parent))
    external_staging = None
    external_staging_file = None
    try:
        # Determine logical export path (final location) and backend write path (staging)
        export_path = None
        backend_write_path = None
        is_external_export = False
        
        if config.classical_solve.model_export_enabled:
            requested = config.classical_solve.model_export_path
            if requested is not None and (not isinstance(requested, str) or not requested.strip()):
                raise ValueError("Model export path must be non-blank.")
            
            if requested is not None:
                # External export: user specified a custom path
                export_path = Path(requested).resolve()
                if export_path.suffix.lower() not in {".lp", ".mps"}:
                    raise ValueError("Model export requires an .lp or .mps file path.")
                if export_path.is_relative_to(destination.resolve()):
                    raise ValueError("Model export must be directly inside the run directory.")
                if export_path.exists():
                    raise FileExistsError(f"Model export already exists: {export_path}")
                # Create staging directory for external export
                external_staging = Path(mkdtemp(prefix=".qreduce-export.", dir=export_path.parent))
                external_staging_file = external_staging / export_path.name
                backend_write_path = str(external_staging_file)
                is_external_export = True
            else:
                # Internal export: default to residual_model.lp in run directory
                export_path = destination.resolve() / "residual_model.lp"
                # Backend writes to staging, which gets atomically moved to destination
                backend_write_path = str(temporary_root / "residual_model.lp")
            
            # Update config with logical path (for manifest), actual write uses backend_write_path
            config = replace(config, classical_solve=replace(
                config.classical_solve, model_export_path=str(export_path)
            ))

        # Execute unified pipeline - pass staging path for backend to write to
        result = run_pipeline(
            problem,
            adapter,
            config,
            mis_solver_registry=mis_solver_registry,
            classical_solver_registry=classical_solver_registry,
            _model_export_write_path=backend_write_path,
        )

        # Check if export succeeded and handle external publish
        exported_file = None
        if backend_write_path:
            staging_file = Path(backend_write_path)
            if staging_file.is_file():
                exported_file = staging_file
                if is_external_export and external_staging_file:
                    # Move external export to final location before run directory publish
                    # This ensures the external file is published even if run directory
                    # publish fails (but external file not removed on such failure)
                    os.replace(external_staging_file, export_path)
                    exported_file = export_path

        _write_artifacts(
            temporary_root,
            experiment_id,
            problem,
            result,
            experiment_metadata or {},
            exported_file,
            export_path,
            is_external_export,
        )
        os.replace(temporary_root, destination)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        # Clean up external staging file if it wasn't published yet
        if external_staging_file and external_staging_file.is_file():
            external_staging_file.unlink(missing_ok=True)
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
    result: PipelineRunResult,
    experiment_metadata: Mapping[str, object],
    exported: Path | None,
    export_path: Path | None,
    external_export: bool,
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

    # Write per-round results if reduction was applied
    if result.round_results:
        for round_result in result.round_results:
            files[f"round_{round_result.round_index:02d}_result.json"] = round_result.to_dict()

    # Write recovery attempts if present
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

    # Serialize fixing_manifest for the manifest (if present)
    fixing_manifest_data = None
    if result.cumulative_fixing_manifest is not None:
        fixing_manifest_data = to_primitive(result.cumulative_fixing_manifest)

    manifest: dict[str, object] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "producer_version": _producer_version(),
        "created_at": utc_created_at(),
        "experiment_id": experiment_id,
        "run_id": result.run_result.run_id,
        "run_status": result.run_result.run_status.value,
        "round_count": result.reduction_round_count,
        "is_classical_only": result.is_classical_only,
        "has_reduction": result.has_reduction,
        "recovery_attempt_count": len(result.recovery_attempts),
        "config_hash": result.run_result.config_hash,
        "policy_provenance": config["policy_provenance"],
        "fixing_manifest": fixing_manifest_data,
        "files": content_hashes,
        "model_export": model_export,
    }

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
