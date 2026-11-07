"""Classical-backend integration boundaries for QReduce."""

from .cplex_capability import CplexRuntimeCapability, probe_cplex_runtime

__all__ = ["CplexRuntimeCapability", "probe_cplex_runtime"]