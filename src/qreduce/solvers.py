"""Stable public identifiers for solver implementations bundled with QReduce."""

from enum import StrEnum


class BuiltinMISSolverId(StrEnum):
    """Built-in solvers for the MWIS reduction problem."""

    LOCAL_GREEDY = "local_greedy"


class BuiltinClassicalSolverId(StrEnum):
    """Built-in solvers for the residual classical optimization problem."""

    CPLEX = "cplex"