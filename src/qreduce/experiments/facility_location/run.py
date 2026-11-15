"""Command-line entry point for facility location experiments."""

import argparse
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from qreduce.experiments.runner import run_experiment
from qreduce.models import (
    ClassicalSolveOptions,
    LambdaEdgePolicy,
    MISExecutionOptions,
    ReductionPolicy,
    ResolvedRunConfig,
    RunIdentity,
)
from qreduce.status import PostcheckMode

from .adapter import FacilityLocationAdapter
from .datasets import identify_reference, parse_or_library
from .graph_policy import FacilityLocationGraphPolicy


def run(instance, run_id, *, output_root="outputs/facility_location", rounds=0, solver="scip", mis_solver="local_greedy", seed=7, budget=60.0, cap=None, protect_all=False, recovery_attempts=0, min_reduction_ratio=0.1, policy=None, model_export=False):
    started = perf_counter()
    data = Path(instance).read_bytes()
    problem = parse_or_library(data.decode("ascii"))
    parse_seconds = perf_counter() - started
    policy = policy or FacilityLocationGraphPolicy()
    config = ResolvedRunConfig(
        schema_version="1.0",
        reduction=ReductionPolicy(max_reduction_rounds=rounds, candidate_domain_min_items=1, candidate_domain_max_items=cap if cap is not None else len(problem.capacities), num_source_mis_candidates=1, min_reduction_ratio=min_reduction_ratio, target_binary_variables=1, max_end_to_end_runtime_seconds=budget, recovery_policy_on_domain_too_small="retry_with_larger_domain" if recovery_attempts else "fail", recovery_policy_on_infeasible="retry_with_larger_domain" if recovery_attempts else "fail", max_recovery_attempts=recovery_attempts),
        lambda_edge=2.0, lambda_edge_policy=LambdaEdgePolicy("standard", "1", 2.0), allow_noncertifying_penalty=False,
        mis_solver_id=mis_solver, mis_execution=MISExecutionOptions(1, seed, 1, False, 0, 0.0, 20),
        classical_solve=ClassicalSolveOptions(classical_solver_id=solver, time_limit_seconds=budget, mip_gap_tolerance=None, threads=1, model_export_enabled=model_export, primal_feasibility_tolerance=1e-6, integrality_tolerance=1e-6, objective_recomputation_absolute_tolerance=1e-6, objective_recomputation_relative_tolerance=1e-6, postcheck_mode=PostcheckMode.STRICT, random_seed=seed),
        run_identity=RunIdentity(run_id),
    )
    metadata = {"input_path": str(Path(instance).resolve()), "sha256": sha256(data).hexdigest(), "reference": identify_reference(data), "parse_seconds": parse_seconds, "graph_policy": policy, "formulation": "fractional-capacitated-v1", "graph_build_seconds": 0.0}
    adapter = FacilityLocationAdapter(policy, protect_all=protect_all, timing_metadata=metadata)
    return run_experiment("facility-location", problem, adapter, config, output_root=output_root, experiment_metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="outputs/facility_location")
    parser.add_argument("--rounds", type=int, default=0)
    parser.add_argument("--solver", default="scip")
    parser.add_argument("--mis-solver", default="local_greedy")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=float, default=60)
    parser.add_argument("--cap", type=int)
    parser.add_argument("--protect-all", action="store_true")
    parser.add_argument("--recovery-attempts", type=int, default=0)
    parser.add_argument("--min-reduction-ratio", type=float, default=0.1)
    parser.add_argument("--model-export", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--epsilon", type=float, default=0.01)
    parser.add_argument("--profile-fraction", type=float, default=0.5)
    parser.add_argument("--overlap-threshold", type=float, default=0.5)
    parser.add_argument("--capacity-difference", type=float, default=0.25)
    args = parser.parse_args()
    policy = FacilityLocationGraphPolicy(args.alpha, args.epsilon, args.profile_fraction, args.overlap_threshold, args.capacity_difference)
    result = run(args.instance, args.run_id, output_root=args.output_root, rounds=args.rounds, solver=args.solver, mis_solver=args.mis_solver, seed=args.seed, budget=args.budget, cap=args.cap, protect_all=args.protect_all, recovery_attempts=args.recovery_attempts, min_reduction_ratio=args.min_reduction_ratio, model_export=args.model_export, policy=policy)
    print(result.run_directory)
    print(result.result.run_result.run_status.value)
    if result.result.run_result.run_status.value not in {"success", "partial_success"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()