"""Runner that persists complete repository experiments for later notebook analysis."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from qreduce.artifacts.metadata import (
    pretty_json,
    redact_metadata,
    sha256_hex,
    to_primitive,
    utc_created_at,
)
from qreduce.classical import ClassicalSolverRegistry
from qreduce.domains import ReducibleProblemAdapter
from qreduce.experiments.artifacts import ARTIFACT_SCHEMA_VERSION
from qreduce.mis import MISSolverRegistry
from qreduce.models import ResolvedRunConfig
from qreduce.pipeline import SinglePassRunResult, run_single_pass


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """One completed repository experiment, including its published artifact directory."""

    experiment_id: str
    run_directory: Path
    result: SinglePassRunResult


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
    """

    _require_identifier(experiment_id, "experiment_id")
    run_id = config.run_identity.run_id
    _require_identifier(run_id, "config.run_identity.run_id")
    destination = Path(output_root) / experiment_id / run_id
    if destination.exists():
        raise FileExistsError(
            f"Experiment artifact directory already exists: {destination}"
        )

    result = run_single_pass(
        problem,
        adapter,
        config,
        mis_solver_registry=mis_solver_registry,
        classical_solver_registry=classical_solver_registry,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(mkdtemp(prefix=f".{run_id}.", dir=destination.parent))
    try:
        _write_artifacts(
            temporary_root,
            experiment_id,
            problem,
            result,
            experiment_metadata or {},
        )
        os.replace(temporary_root, destination)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return ExperimentRun(
        experiment_id=experiment_id, run_directory=destination, result=result
    )


def _write_artifacts(
    directory: Path,
    experiment_id: str,
    problem: object,
    result: SinglePassRunResult,
    experiment_metadata: Mapping[str, object],
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
    compilation = result.mis_compilation_result
    if compilation is not None and compilation.compiled_job is not None:
        files["canonical_mwis_problem.json"] = (
            compilation.compiled_job.compiled_problem.to_dict()
        )

    content_hashes: dict[str, str] = {}
    for filename, contents in files.items():
        _write_json(directory / filename, contents)
        content_hashes[filename] = sha256_hex(contents)

    manifest: dict[str, object] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "producer_version": _producer_version(),
        "created_at": utc_created_at(),
        "experiment_id": experiment_id,
        "run_id": result.run_result.run_id,
        "run_status": result.run_result.run_status.value,
        "config_hash": result.run_result.config_hash,
        "files": content_hashes,
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
