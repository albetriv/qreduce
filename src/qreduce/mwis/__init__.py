"""Canonical, provider-independent MWIS graph, QUBO, Ising and diagnostics."""

from qreduce.mwis.exact import ExactMWISResult, solve_exact_mwis
from qreduce.mwis.graph import CanonicalMWISProblem, ReductionGraph
from qreduce.mwis.ising import CanonicalIsing, qubo_to_ising
from qreduce.mwis.qubo import CanonicalQubo, build_mwis_qubo
from qreduce.mwis.validation import (
    MWISValidationError,
    PenaltyValidationResult,
    SelectionValidationResult,
    validate_binary_selection,
    validate_edge_penalty,
)

__all__ = [
    "CanonicalIsing",
    "CanonicalMWISProblem",
    "CanonicalQubo",
    "ExactMWISResult",
    "MWISValidationError",
    "PenaltyValidationResult",
    "ReductionGraph",
    "SelectionValidationResult",
    "build_mwis_qubo",
    "qubo_to_ising",
    "solve_exact_mwis",
    "validate_binary_selection",
    "validate_edge_penalty",
]