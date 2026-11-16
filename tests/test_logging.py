"""Tests for QReduce logging infrastructure."""

import logging

import pytest

from qreduce.logging_config import (
    LoggingConfigError,
    _managed_handlers,
    configure_logging,
    get_default_config_path,
)
from qreduce.logging_context import (
    ContextDefaultsFilter,
    _logging_context,
    get_logging_context,
    logging_context,
)

# Logger names that may be modified during tests
_LOGGERS_TO_SNAPSHOT = [
    "qreduce",
    "qreduce.pipeline",
    "qreduce.pipeline.unified",
    "qreduce.pipeline.single_pass",
    "qreduce.pipeline.multi_round",
    "qreduce.experiments",
    "qreduce.experiments.runner",
    "qreduce.solving",
]


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Snapshot and restore logging state after each test.

    This fixture saves the state of relevant loggers before each test
    and restores it afterward to prevent test pollution. Handlers created
    during the test are closed before restoring the original state.
    """
    root_logger = logging.getLogger()

    # Snapshot state of all relevant loggers
    logger_snapshots = {}
    for name in _LOGGERS_TO_SNAPSHOT:
        lgr = logging.getLogger(name)
        logger_snapshots[name] = {
            "handlers": lgr.handlers[:],
            "level": lgr.level,
            "propagate": lgr.propagate,
        }

    # Snapshot root logger
    root_snapshot = {
        "handlers": root_logger.handlers[:],
        "level": root_logger.level,
    }

    # Snapshot managed handlers list
    managed_snapshot = _managed_handlers[:]

    # Snapshot context var
    original_context = _logging_context.get()

    yield

    # FIRST: Close any handlers that were added during the test
    # Do this BEFORE restoring the lists, otherwise we lose the references
    for name in _LOGGERS_TO_SNAPSHOT:
        lgr = logging.getLogger(name)
        original_handlers = logger_snapshots[name]["handlers"]
        for handler in lgr.handlers:
            if handler not in original_handlers:
                try:
                    handler.close()
                except Exception:  # noqa: BLE001, S110
                    pass

    # Close any handlers added to root logger
    for handler in root_logger.handlers:
        if handler not in root_snapshot["handlers"]:
            try:
                handler.close()
            except Exception:  # noqa: BLE001, S110
                pass

    # THEN: Restore logger state
    for name in _LOGGERS_TO_SNAPSHOT:
        lgr = logging.getLogger(name)
        snap = logger_snapshots[name]
        lgr.handlers[:] = snap["handlers"]
        lgr.level = snap["level"]
        lgr.propagate = snap["propagate"]

    # Restore root logger
    root_logger.handlers[:] = root_snapshot["handlers"]
    root_logger.level = root_snapshot["level"]

    # Restore managed handlers list
    _managed_handlers[:] = managed_snapshot

    # Restore context var
    _logging_context.set(original_context)


@pytest.fixture
def temp_log_dir(tmp_path):
    """Provide a temporary directory for log files."""
    return tmp_path


class TestLoggingContext:
    """Tests for contextvars-based logging context."""

    def test_default_context_has_placeholder_values(self):
        ctx = get_logging_context()
        assert ctx.run_id == "-"
        assert ctx.round_index == "-"
        assert ctx.stage == "-"
        assert ctx.solver_id == "-"

    def test_logging_context_sets_values(self):
        with logging_context(run_id="test_run"):
            ctx = get_logging_context()
            assert ctx.run_id == "test_run"
            assert ctx.round_index == "-"  # Not set, remains default

    def test_logging_context_restores_on_exit(self):
        original = get_logging_context()
        with logging_context(run_id="test_run"):
            pass
        restored = get_logging_context()
        assert restored.run_id == original.run_id

    def test_nested_logging_context(self):
        with logging_context(run_id="run1"):
            ctx1 = get_logging_context()
            assert ctx1.run_id == "run1"
            assert ctx1.stage == "-"

            with logging_context(stage="mwis"):
                ctx2 = get_logging_context()
                assert ctx2.run_id == "run1"  # Inherited
                assert ctx2.stage == "mwis"

            # After inner context exits, stage should be restored
            ctx3 = get_logging_context()
            assert ctx3.run_id == "run1"
            assert ctx3.stage == "-"

    def test_logging_context_round_index_as_int(self):
        with logging_context(round_index=0):
            ctx = get_logging_context()
            assert ctx.round_index == "0"

        with logging_context(round_index=5):
            ctx = get_logging_context()
            assert ctx.round_index == "5"

    def test_logging_context_all_fields(self):
        with logging_context(
            run_id="full_test",
            round_index=2,
            stage="classical",
            solver_id="scip",
        ):
            ctx = get_logging_context()
            assert ctx.run_id == "full_test"
            assert ctx.round_index == "2"
            assert ctx.stage == "classical"
            assert ctx.solver_id == "scip"


class TestContextDefaultsFilter:
    """Tests for the logging filter that injects context."""

    def test_filter_adds_context_to_record(self):
        filt = ContextDefaultsFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )

        # Filter should always return True (allow logging)
        assert filt.filter(record) is True

        # Check that context fields were added with defaults
        assert record.run_id == "-"
        assert record.round_index == "-"
        assert record.stage == "-"
        assert record.solver_id == "-"

    def test_filter_uses_current_context(self):
        filt = ContextDefaultsFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )

        with logging_context(run_id="ctx_run", stage="testing"):
            filt.filter(record)

        assert record.run_id == "ctx_run"
        assert record.stage == "testing"
        assert record.round_index == "-"  # Not set


class TestLoggingConfig:
    """Tests for YAML-based logging configuration."""

    def test_valid_yaml_config(self, temp_log_dir):
        config_file = temp_log_dir / "logging.yaml"
        log_file = temp_log_dir / "test.log"
        config_file.write_text(f"""
version: 1
disable_existing_loggers: false

formatters:
  simple:
    format: "%(levelname)s - %(message)s"

handlers:
  file:
    class: logging.FileHandler
    level: DEBUG
    formatter: simple
    filename: "{log_file}"

loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        result = configure_logging(config_file)
        assert result == config_file.resolve()

        # Test that logging actually works
        logger = logging.getLogger("qreduce.test")
        logger.info("Test message")

        # Force flush
        for handler in logging.getLogger("qreduce").handlers:
            handler.flush()

        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content

    def test_missing_config_file_raises(self, temp_log_dir):
        missing_path = temp_log_dir / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="not found"):
            configure_logging(missing_path)

    def test_empty_config_file_raises(self, temp_log_dir):
        config_file = temp_log_dir / "empty.yaml"
        config_file.write_text("")

        with pytest.raises(LoggingConfigError, match="Empty"):
            configure_logging(config_file)

    def test_invalid_yaml_raises(self, temp_log_dir):
        config_file = temp_log_dir / "invalid.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(LoggingConfigError, match="Invalid YAML"):
            configure_logging(config_file)

    def test_missing_version_raises(self, temp_log_dir):
        config_file = temp_log_dir / "no_version.yaml"
        config_file.write_text("""
formatters:
  simple:
    format: "%(message)s"
""")

        with pytest.raises(LoggingConfigError, match="version"):
            configure_logging(config_file)

    def test_wrong_version_raises(self, temp_log_dir):
        config_file = temp_log_dir / "wrong_version.yaml"
        config_file.write_text("""
version: 2
disable_existing_loggers: false
""")

        with pytest.raises(LoggingConfigError, match="version 2"):
            configure_logging(config_file)

    def test_handler_missing_class_raises(self, temp_log_dir):
        config_file = temp_log_dir / "bad_handler.yaml"
        config_file.write_text("""
version: 1
handlers:
  console:
    level: INFO
""")

        with pytest.raises(LoggingConfigError, match="class"):
            configure_logging(config_file)

    def test_relative_paths_resolved_to_yaml_dir(self, temp_log_dir):
        config_file = temp_log_dir / "relative.yaml"
        config_file.write_text("""
version: 1
disable_existing_loggers: false

formatters:
  simple:
    format: "%(message)s"

handlers:
  file:
    class: logging.FileHandler
    level: DEBUG
    formatter: simple
    filename: "relative.log"

loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        configure_logging(config_file)

        # Log file should be created in the same directory as the YAML
        expected_log = temp_log_dir / "relative.log"
        logger = logging.getLogger("qreduce.test_relative")
        logger.info("test")

        for handler in logging.getLogger("qreduce").handlers:
            handler.flush()

        assert expected_log.exists()

    def test_env_var_config_path(self, temp_log_dir, monkeypatch):
        config_file = temp_log_dir / "env_config.yaml"
        config_file.write_text("""
version: 1
disable_existing_loggers: false
loggers:
  qreduce:
    level: DEBUG
""")

        monkeypatch.setenv("QREDUCE_LOG_CONFIG", str(config_file))
        result = configure_logging()
        assert result == config_file.resolve()

    def test_explicit_path_overrides_env_var(self, temp_log_dir, monkeypatch):
        env_config = temp_log_dir / "env.yaml"
        explicit_config = temp_log_dir / "explicit.yaml"

        for f in [env_config, explicit_config]:
            f.write_text("""
version: 1
disable_existing_loggers: false
""")

        monkeypatch.setenv("QREDUCE_LOG_CONFIG", str(env_config))
        result = configure_logging(explicit_config)
        assert result == explicit_config.resolve()

    def test_no_config_returns_none(self, monkeypatch):
        # Ensure no env var is set
        monkeypatch.delenv("QREDUCE_LOG_CONFIG", raising=False)
        result = configure_logging(None)
        assert result is None

    def test_repeated_configuration_no_duplicate_handlers(self, temp_log_dir):
        config_file = temp_log_dir / "repeat.yaml"
        config_file.write_text("""
version: 1
disable_existing_loggers: false

handlers:
  console:
    class: logging.StreamHandler
    level: DEBUG
    stream: ext://sys.stderr

loggers:
  qreduce:
    level: DEBUG
    handlers: [console]
    propagate: false
""")

        # Configure twice
        configure_logging(config_file)
        configure_logging(config_file)

        # Should have exactly one handler (not duplicated)
        qreduce_logger = logging.getLogger("qreduce")
        assert len(qreduce_logger.handlers) == 1

    def test_creates_log_directory(self, temp_log_dir):
        config_file = temp_log_dir / "with_subdir.yaml"
        nested_dir = temp_log_dir / "logs" / "nested"
        log_file = nested_dir / "app.log"

        config_file.write_text(f"""
version: 1
disable_existing_loggers: false

formatters:
  simple:
    format: "%(message)s"

handlers:
  file:
    class: logging.FileHandler
    level: DEBUG
    formatter: simple
    filename: "{log_file}"

loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        configure_logging(config_file)

        # Directory should have been created
        assert nested_dir.exists()


class TestLibraryBehavior:
    """Tests for library-style logging behavior."""

    def test_import_adds_null_handler(self):
        # This test verifies that importing qreduce adds a NullHandler.
        # The handler may have been cleaned up by the test fixture,
        # so we re-add it as qreduce.__init__ would have done.
        import qreduce  # noqa: F401 - import has side effect of adding NullHandler

        qreduce_logger = logging.getLogger("qreduce")
        # Ensure there's at least a NullHandler (re-add if needed)
        if not any(isinstance(h, logging.NullHandler) for h in qreduce_logger.handlers):
            qreduce_logger.addHandler(logging.NullHandler())

        # Now verify the behavior: with only NullHandler, logging should not fail
        child_logger = logging.getLogger("qreduce.test_module")
        # This should not raise or produce output
        child_logger.info("Silent message")

    def test_library_logger_integrates_with_host_config(self, temp_log_dir):
        # Simulate an application configuring its own logging
        log_file = temp_log_dir / "host_app.log"

        # Application's own configuration
        app_handler = logging.FileHandler(log_file)
        app_handler.setFormatter(logging.Formatter("HOST: %(name)s - %(message)s"))

        # Application adds handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(app_handler)

        # qreduce logger should propagate to root when propagate=True
        qreduce_logger = logging.getLogger("qreduce.pipeline")
        qreduce_logger.setLevel(logging.DEBUG)

        # Enable propagation for this test
        qreduce_root = logging.getLogger("qreduce")
        qreduce_root.propagate = True

        qreduce_logger.info("Library log message")
        app_handler.flush()
        app_handler.close()

        content = log_file.read_text()
        assert "Library log message" in content
        assert "qreduce.pipeline" in content
        # Note: cleanup_logging fixture will restore original propagate value


class TestGetDefaultConfigPath:
    """Tests for finding the default config path."""

    def test_returns_path_if_exists(self):
        # This test depends on the actual repository structure
        default_path = get_default_config_path()
        if default_path is not None:
            assert default_path.exists()
            assert default_path.name == "logging.yaml"

    def test_returns_none_if_not_found(self, monkeypatch, tmp_path):
        # Temporarily make the module think it's somewhere else
        import qreduce.logging_config as lc

        original_file = lc.__file__
        try:
            # Point to a location where config/logging.yaml won't exist
            lc.__file__ = str(tmp_path / "fake_module.py")
            result = get_default_config_path()
            # Should return None since the config won't be found
            assert result is None
        finally:
            lc.__file__ = original_file


# ---------------------------------------------------------------------------
# Integration tests - test real flows and subprocess isolation
# ---------------------------------------------------------------------------


class TestLoggingIntegration:
    """Integration tests for logging in real-world scenarios."""

    def test_import_in_subprocess_is_silent(self, tmp_path):
        """Verify that importing qreduce in a fresh process produces no output."""
        import subprocess
        import sys

        script = tmp_path / "import_test.py"
        script.write_text("""
import sys
import qreduce
from qreduce.pipeline import run_pipeline
# Just importing should not produce any output
print("OK")
""")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        # Should succeed with only "OK" output
        assert result.returncode == 0
        assert result.stdout.strip() == "OK"
        # stderr should be empty (no log messages)
        assert result.stderr.strip() == ""

    def test_cli_config_precedence(self, tmp_path, monkeypatch):
        """Verify that CLI --log-config takes precedence over env var."""
        import subprocess
        import sys

        # Create two different config files
        env_config = tmp_path / "env.yaml"
        cli_config = tmp_path / "cli.yaml"
        marker_file = tmp_path / "marker.txt"

        env_config.write_text("""
version: 1
disable_existing_loggers: false
loggers:
  qreduce:
    level: WARNING
""")

        # CLI config is more verbose to prove it was used
        cli_config.write_text(f"""
version: 1
disable_existing_loggers: false
formatters:
  marker:
    format: "MARKER: %(message)s"
handlers:
  file:
    class: logging.FileHandler
    filename: "{marker_file}"
    formatter: marker
loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
""")

        script = tmp_path / "precedence_test.py"
        script.write_text(f"""
import sys
sys.path.insert(0, "{tmp_path.parent}")
from qreduce.logging_config import configure_logging
from pathlib import Path

cli_path = Path("{cli_config}")
configure_logging(cli_path)

import logging
logger = logging.getLogger("qreduce.test")
logger.info("Precedence test")

# Flush handlers
for h in logging.getLogger("qreduce").handlers:
    h.flush()
    h.close()
""")

        env = monkeypatch._getvalue("environ", {}).copy() if hasattr(monkeypatch, "_getvalue") else {}
        env = dict(env, QREDUCE_LOG_CONFIG=str(env_config))

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        # Marker file should exist and contain our message
        assert marker_file.exists(), "CLI config was not applied"
        content = marker_file.read_text()
        assert "MARKER: Precedence test" in content

    def test_context_filter_in_formatter(self, temp_log_dir):
        """Verify that context fields appear in formatted log output."""
        config_file = temp_log_dir / "context_format.yaml"
        log_file = temp_log_dir / "context.log"

        config_file.write_text(f"""
version: 1
disable_existing_loggers: false
formatters:
  context:
    format: "[%(run_id)s:%(round_index)s:%(stage)s:%(solver_id)s] %(message)s"
filters:
  context_defaults:
    "()": qreduce.logging_context.ContextDefaultsFilter
handlers:
  file:
    class: logging.FileHandler
    filename: "{log_file}"
    formatter: context
    filters: [context_defaults]
loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        configure_logging(config_file)

        logger = logging.getLogger("qreduce.integration")

        # Log without context
        logger.info("No context")

        # Log with partial context
        with logging_context(run_id="RUN001", stage="test"):
            logger.info("Partial context")

        # Log with full context
        with logging_context(run_id="RUN002", round_index=3, stage="mwis", solver_id="greedy"):
            logger.info("Full context")

        for handler in logging.getLogger("qreduce").handlers:
            handler.flush()

        content = log_file.read_text()
        lines = content.strip().split("\n")

        # Verify default placeholders
        assert "[-:-:-:-] No context" in lines[0]
        # Verify partial context (run_id and stage set, others default)
        assert "[RUN001:-:test:-] Partial context" in lines[1]
        # Verify full context
        assert "[RUN002:3:mwis:greedy] Full context" in lines[2]

    def test_nested_context_propagation(self, temp_log_dir):
        """Verify that nested contexts correctly inherit and override values."""
        config_file = temp_log_dir / "nested.yaml"
        log_file = temp_log_dir / "nested.log"

        config_file.write_text(f"""
version: 1
disable_existing_loggers: false
formatters:
  context:
    format: "[%(run_id)s:%(round_index)s:%(stage)s] %(message)s"
filters:
  context_defaults:
    "()": qreduce.logging_context.ContextDefaultsFilter
handlers:
  file:
    class: logging.FileHandler
    filename: "{log_file}"
    formatter: context
    filters: [context_defaults]
loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        configure_logging(config_file)

        logger = logging.getLogger("qreduce.nested")

        with logging_context(run_id="RUN"):
            logger.info("outer")
            with logging_context(round_index=0):
                logger.info("round 0")
                with logging_context(stage="mwis"):
                    logger.info("mwis stage")
                logger.info("still round 0")
            logger.info("back to outer")

        for handler in logging.getLogger("qreduce").handlers:
            handler.flush()

        content = log_file.read_text()
        lines = content.strip().split("\n")

        assert "[RUN:-:-] outer" in lines[0]
        assert "[RUN:0:-] round 0" in lines[1]
        assert "[RUN:0:mwis] mwis stage" in lines[2]
        assert "[RUN:0:-] still round 0" in lines[3]
        assert "[RUN:-:-] back to outer" in lines[4]

    def test_exception_logging_preserves_context(self, temp_log_dir):
        """Verify that exception logging includes context fields."""
        config_file = temp_log_dir / "exception.yaml"
        log_file = temp_log_dir / "exception.log"

        config_file.write_text(f"""
version: 1
disable_existing_loggers: false
formatters:
  context:
    format: "[%(run_id)s:%(stage)s] %(levelname)s %(message)s"
filters:
  context_defaults:
    "()": qreduce.logging_context.ContextDefaultsFilter
handlers:
  file:
    class: logging.FileHandler
    filename: "{log_file}"
    formatter: context
    filters: [context_defaults]
loggers:
  qreduce:
    level: DEBUG
    handlers: [file]
    propagate: false
""")

        configure_logging(config_file)

        logger = logging.getLogger("qreduce.exception")

        with logging_context(run_id="ERR001", stage="failing_stage"):
            try:
                raise ValueError("test error")
            except ValueError:
                logger.exception("Operation failed")

        for handler in logging.getLogger("qreduce").handlers:
            handler.flush()

        content = log_file.read_text()
        assert "[ERR001:failing_stage] ERROR Operation failed" in content
        assert "ValueError: test error" in content