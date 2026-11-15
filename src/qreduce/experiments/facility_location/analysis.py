"""Read persisted facility-location artifacts without rerunning a solver."""

from qreduce.experiments import load_experiment_run


def summary(run_directory):
    artifacts = load_experiment_run(run_directory)
    if artifacts.manifest["experiment_id"] != "facility-location":
        raise ValueError("Not a facility-location experiment")
    result = artifacts.result
    classical = result.get("classical_result") or {}
    reference = artifacts.experiment_metadata.get("reference")
    claimed = classical.get("objective_value")
    postcheck = result.get("postcheck_result") or {}
    objective = postcheck.get("objective_recomputed") if postcheck.get("postcheck_feasible") else None
    difference = objective - reference["objective"] if objective is not None and reference else None
    original = result.get("original_variable_counts") or {}
    residual = result.get("residual_variable_counts") or {}
    metrics = result.get("metrics") or {}
    domain = {entry["metric_id"]: entry["value"] for entry in (result.get("domain_evaluation_metrics") or [])}
    row = {"run_id": artifacts.manifest["run_id"], "status": artifacts.manifest["run_status"], "rounds": artifacts.reduction_round_count, "recovery_attempts": len(artifacts.recovery_attempts), "solver_objective": claimed, "objective": objective, "reference": reference, "difference_from_reference": difference, "solver_gap": classical.get("gap"), "metrics": metrics, "domain_metrics": domain, "postcheck": postcheck, "graph_build_seconds": artifacts.experiment_metadata.get("graph_build_seconds"), "end_to_end_seconds": metrics.get("end_to_end_runtime_seconds")}
    for kind in ("binary_free", "continuous_free"):
        before, after = original.get(kind), residual.get(kind)
        row[f"original_{kind}"] = before
        row[f"residual_{kind}"] = after
        row[f"reduction_{kind}"] = 1 - after / before if before and after is not None else None
    row.update(domain)
    return row