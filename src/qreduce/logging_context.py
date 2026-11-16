"""Context management for QReduce logging.

This module provides thread-safe context propagation for logging using contextvars.
It enables logging of execution context (run_id, round_index, stage, solver_id)
without passing these values through all API calls.

Usage in pipeline code:
    from qreduce.logging_context import logging_context

    with logging_context(run_id="run001", stage="mwis_execution"):
        logger.info("Starting MWIS execution")
        # Logs will include run_id=run001, stage=mwis_execution
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class LoggingContext:
    """Immutable snapshot of logging context values.

    All fields default to "-" for safe formatting when not set.
    """

    run_id: str = "-"
    round_index: str = "-"
    stage: str = "-"
    solver_id: str = "-"

    # Class-level defaults for formatter
    DEFAULTS: ClassVar[dict[str, str]] = field(
        default={
            "run_id": "-",
            "round_index": "-",
            "stage": "-",
            "solver_id": "-",
        },
        repr=False,
    )


# Thread-safe context variable holding the current logging context
# Note: LoggingContext is frozen/immutable, so the default is safe.
_logging_context: ContextVar[LoggingContext] = ContextVar(
    "qreduce_logging_context",
    default=LoggingContext(),  # noqa: B039 - LoggingContext is frozen/immutable
)


def get_logging_context() -> LoggingContext:
    """Return the current logging context."""
    return _logging_context.get()


def set_logging_context(ctx: LoggingContext) -> Token[LoggingContext]:
    """Set the logging context and return a token for restoration."""
    return _logging_context.set(ctx)


def reset_logging_context(token: Token[LoggingContext]) -> None:
    """Reset the logging context to its previous value."""
    _logging_context.reset(token)


@contextmanager
def logging_context(
    *,
    run_id: str | None = None,
    round_index: int | str | None = None,
    stage: str | None = None,
    solver_id: str | None = None,
):
    """Context manager to set logging context fields for the duration of a block.

    Fields not specified retain their current values. This allows nested contexts
    to refine the context progressively (e.g., set run_id at run start, then
    add round_index within each round).

    Args:
        run_id: Unique identifier for the current run.
        round_index: Zero-based index of the current reduction round.
        stage: Current pipeline stage name.
        solver_id: Identifier of the active solver.

    Yields:
        None. The context is accessible via get_logging_context() or the filter.
    """
    current = _logging_context.get()

    # Build updates dict with only provided values
    updates: dict[str, str] = {}
    if run_id is not None:
        updates["run_id"] = run_id
    if round_index is not None:
        updates["round_index"] = str(round_index)
    if stage is not None:
        updates["stage"] = stage
    if solver_id is not None:
        updates["solver_id"] = solver_id

    if updates:
        new_context = replace(current, **updates)
        token = _logging_context.set(new_context)
    else:
        token = None

    try:
        yield
    finally:
        if token is not None:
            _logging_context.reset(token)


class ContextDefaultsFilter(logging.Filter):
    """Logging filter that adds context fields to log records.

    This filter ensures that context fields (run_id, round_index, stage, solver_id)
    are always present in log records, using default values when the context is not set.
    This prevents KeyError when using format strings that reference these fields.

    Usage in YAML config:
        filters:
          context_defaults:
            "()": qreduce.logging_context.ContextDefaultsFilter

        handlers:
          console:
            filters: [context_defaults]
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context fields to the log record.

        Returns True to allow the record to be logged (this filter never blocks).
        """
        ctx = _logging_context.get()
        record.run_id = ctx.run_id
        record.round_index = ctx.round_index
        record.stage = ctx.stage
        record.solver_id = ctx.solver_id
        return True


# Convenience function for modules to get a logger with context awareness
def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name.

    This is a simple wrapper around logging.getLogger() for consistency.
    The context is injected by the ContextDefaultsFilter, not by the logger itself.

    Args:
        name: Logger name, typically __name__.

    Returns:
        A Logger instance.
    """
    return logging.getLogger(name)
