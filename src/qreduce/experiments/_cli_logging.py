"""Shared logging for experiment CLI entry points."""

import shlex
import sys

from qreduce.logging_context import get_logger, logging_context

logger = get_logger(__name__)


def log_run_command(run_id: str) -> None:
    """Log the Python invocation at the start of an experiment CLI run."""
    with logging_context(run_id=run_id, stage="experiment_cli"):
        # Unlike sys.argv, orig_argv preserves interpreter flags and the -m module name.
        # Use sys.executable to keep the virtualenv when a launcher rewrites argv[0].
        command = [sys.executable or sys.orig_argv[0], *sys.orig_argv[1:]]
        logger.debug("Experiment command line: %s", shlex.join(command))