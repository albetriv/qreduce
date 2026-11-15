"""Reproducible matrix of facility-location comparisons."""

import json
import os
from pathlib import Path

from .analysis import summary
from .datasets import load_or_library
from .run import run


def benchmark(instance, prefix, *, output_root="outputs/facility_location", seed=7, budget=60, solver="scip", mis_solver="local_greedy", policy=None, recovery_attempts=15, cap=None):
    if not prefix or Path(prefix).name != prefix:
        raise ValueError("prefix must be a single path component")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / f"{prefix}-benchmark.json"
    if report_path.exists():
        raise FileExistsError(report_path)
    scenarios = {
        "baseline": {"rounds": 0},
        "all_protected": {"rounds": 1, "protect_all": True},
        "single": {"rounds": 1},
        "single_recovery": {"rounds": 1, "recovery_attempts": recovery_attempts},
        "multi_recovery": {"rounds": 3, "recovery_attempts": recovery_attempts},
    }
    results = {}
    report = {"instance": str(instance), "seed": seed, "budget_seconds": budget, "solver": solver, "mis_solver": mis_solver, "recovery_attempts": recovery_attempts, "results": results}

    def checkpoint():
        temporary = report_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, report_path)

    checkpoint()
    for name, options in scenarios.items():
        scenario_cap = None if name == "all_protected" else cap
        try:
            load_or_library(instance)
        except (OSError, UnicodeError, ValueError) as error:
            results[name] = {"preparation_error": f"{type(error).__name__}: {error}"}
            checkpoint()
            continue
        try:
            result = run(instance, f"{prefix}-{name}", output_root=output_root, seed=seed, budget=budget, solver=solver, mis_solver=mis_solver, policy=policy, cap=scenario_cap, **options)
        except Exception as error:  # noqa: BLE001 - preserve failure classification in benchmark report
            results[name] = {"execution_error": f"{type(error).__name__}: {error}"}
            checkpoint()
            continue
        try:
            results[name] = {"directory": str(result.run_directory), "requested_cap": scenario_cap, **summary(result.run_directory)}
        except Exception as error:  # noqa: BLE001 - preserve completed run if artifact analysis fails
            results[name] = {"directory": str(result.run_directory), "analysis_error": f"{type(error).__name__}: {error}"}
        checkpoint()
    baseline = results.get("baseline", {}).get("objective")
    for value in results.values():
        objective = value.get("objective")
        value["difference_from_baseline"] = objective - baseline if objective is not None and baseline is not None else None
    checkpoint()
    return report