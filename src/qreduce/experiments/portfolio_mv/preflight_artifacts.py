"""Read the original canonical MWIS model for an offline-to-QPU preflight."""

from ast import literal_eval
from collections.abc import Mapping
from pathlib import Path

from qreduce.experiments.artifacts import (
    ExperimentArtifactError,
    first_round_canonical_problem,
    load_experiment_run,
)
from qreduce.experiments.portfolio_mv.analysis import _rebuild_graph
from qreduce.mwis import CanonicalIsing, CanonicalMWISProblem, CanonicalQubo


def _quadratic(raw: object) -> dict[tuple[str, str], float]:
    if isinstance(raw, Mapping):
        terms = ((literal_eval(key), value) for key, value in raw.items())
    elif isinstance(raw, list):
        terms = ((term["edge"], term["coefficient"]) for term in raw)
    else:
        raise ValueError("Invalid persisted quadratic terms.")
    result = {}
    for edge, coefficient in terms:
        if not isinstance(edge, (tuple, list)) or len(edge) != 2 or not all(isinstance(n, str) for n in edge):
            raise ValueError("Invalid persisted quadratic edge.")
        key = (edge[0], edge[1])
        if key in result:
            raise ValueError("Duplicate persisted quadratic edge.")
        result[key] = float(coefficient)
    return result


def load_preflight_problem(run_directory: Path) -> tuple[str, CanonicalMWISProblem]:
    """Load verified artifacts without regenerating any part of the instance."""
    artifacts = load_experiment_run(run_directory)
    data = first_round_canonical_problem(artifacts)
    try:
        graph = _rebuild_graph(data)
        qubo_data, ising_data = data["qubo"], data["ising"]
        if not isinstance(qubo_data, Mapping) or not isinstance(ising_data, Mapping):
            raise ValueError("Invalid persisted QUBO or Ising model.")
        proof = qubo_data["proof_condition_satisfied"]
        if not isinstance(proof, bool):
            raise ValueError("Invalid persisted QUBO proof flag.")
        qubo = CanonicalQubo(
            node_order=tuple(qubo_data["node_order"]),
            linear=qubo_data["linear"],
            quadratic=_quadratic(qubo_data["quadratic"]),
            offset=qubo_data["offset"],
            lambda_edge=qubo_data["lambda_edge"],
            proof_condition_satisfied=proof,
        )
        ising = CanonicalIsing(
            node_order=tuple(ising_data["node_order"]),
            linear=ising_data["linear"],
            quadratic=_quadratic(ising_data["quadratic"]),
            offset=ising_data["offset"],
            binary_to_spin_convention=ising_data["binary_to_spin_convention"],
        )
        problem = CanonicalMWISProblem(graph=graph, qubo=qubo, ising=ising)
    except (KeyError, TypeError, ValueError, SyntaxError, AttributeError, OverflowError) as error:
        raise ExperimentArtifactError("Invalid persisted canonical MWIS problem for round 0.") from error
    return str(artifacts.manifest["run_id"]), problem