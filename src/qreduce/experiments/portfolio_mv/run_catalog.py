"""Publish a local, static UIX catalog of completed mean–variance runs."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from qreduce.experiments.artifacts import ExperimentArtifactError, load_experiment_run
from qreduce.experiments.portfolio_mv.execution import UNIFIED_EXPERIMENT_ID

_BASE_FILES = (
    "run_manifest.json", "problem.json", "run_result.json",
    "config_used.json", "experiment_metadata.json",
)
_ROUND_FILE = re.compile(r"round_[0-9]+_result\.json")


def write_catalog(output_root: Path, destination: Path) -> tuple[int, list[str]]:
    """Write a catalog atomically and report directories that could not be indexed."""
    entries = []
    skipped = []
    for directory in sorted(output_root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            artifacts = load_experiment_run(directory)
            if artifacts.manifest["experiment_id"] != UNIFIED_EXPERIMENT_ID:
                continue
            run_id = artifacts.manifest["run_id"]
            if run_id != directory.name:
                skipped.append(f"{directory.name}: manifest run_id does not match the directory name")
                continue
            names = (*_BASE_FILES, *sorted(
                name for name in artifacts.manifest["files"] if _ROUND_FILE.fullmatch(name)
            ))
            files = {name: (directory / name).read_bytes().decode("utf-8") for name in names}
            entries.append({"id": run_id, "files": files})
        except (ExperimentArtifactError, OSError, UnicodeError) as error:
            skipped.append(f"{directory.name}: {error}")

    # A classic script loads from file:// without fetch. Artifact text is JSON-escaped,
    # not interpolated into executable expressions; embedding text preserves bytes.
    content = "window.QReduceRunCatalog = " + json.dumps(entries, ensure_ascii=True) + ";\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as staging:
        temporary_path = Path(staging.name)
    try:
        temporary_path.write_text(content, encoding="ascii")
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return len(entries), skipped


def main(argv: list[str] | None = None) -> int:
    """Refresh the UIX catalog without running a solver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/portfolio_mv"))
    parser.add_argument("--catalog", type=Path, default=Path("outputs/portfolio_mv/run_catalog.js"))
    args = parser.parse_args(argv)
    try:
        count, skipped = write_catalog(args.output_root, args.catalog)
    except OSError as error:
        print(f"Cannot update UIX catalog: {error}", file=sys.stderr)
        return 1
    for message in skipped:
        print(f"Skipped {message}", file=sys.stderr)
    print(f"{count} run(s) indexed: {args.catalog.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())