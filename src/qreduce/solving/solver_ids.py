"""Stable public identifiers for solver implementations bundled with QReduce."""

from enum import StrEnum


class BuiltinMISSolverId(StrEnum):
    """MIS solvers included with QReduce."""

    LOCAL_GREEDY = "local_greedy"
    DWAVE_SIMULATED_ANNEALING = "dwave_simulated_annealing"


class BuiltinClassicalSolverId(StrEnum):
    """Classical solver integrations included with QReduce."""

    CPLEX = "cplex"
    SCIP = "scip"