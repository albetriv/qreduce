"""Centralized YAML-based logging configuration loader for QReduce.

This module provides utilities to load, validate, and apply logging configuration
from external YAML files. The configuration follows Python's logging.config.dictConfig
schema.

IMPORTANT CONTRACTS:

1. Library import (NullHandler only):
   Importing qreduce adds only a NullHandler to the 'qreduce' logger. No
   configuration is applied, no output is produced. The host application
   maintains full control of its logging configuration.

2. Explicit configuration (process-level):
   Calling configure_logging() applies dictConfig() to the entire process.
   This is designed for CLI entry points that own the process configuration.

   WARNING: dictConfig() may close or reconfigure handlers that were set up
   by the host application before this call. This includes handlers on the
   root logger or other loggers referenced in the YAML configuration.

   If you need to integrate QReduce logging into an existing application
   without affecting the host's handlers, do NOT call configure_logging().
   Instead, configure your application's logging to include the 'qreduce'
   hierarchy as needed.

3. Security:
   The YAML file is loaded with yaml.safe_load() to limit deserialization,
   but dictConfig() can instantiate objects referenced in the file. Only
   load configuration from trusted sources.

4. Reconfiguration:
   Calling configure_logging() multiple times will close handlers that were
   previously created by this configurator (tracked in _managed_handlers)
   before applying the new configuration. This prevents handler duplication
   but does not protect handlers created outside this module.
"""

import logging
import logging.config
import os
from pathlib import Path

import yaml


class LoggingConfigError(Exception):
    """Raised when logging configuration is invalid or cannot be applied."""


# Track handlers created by our configurator for cleanup on reconfiguration
_managed_handlers: list[logging.Handler] = []


def configure_logging(
    config_path: str | Path | None = None,
    *,
    env_var: str = "QREDUCE_LOG_CONFIG",
) -> Path | None:
    """Load and apply logging configuration from a YAML file.

    This function is intended for CLI entry points that own the process
    configuration. It applies dictConfig() which affects the entire logging
    system, not just QReduce loggers.

    Resolution order:
    1. Explicit config_path argument (if provided)
    2. Environment variable (env_var, default QREDUCE_LOG_CONFIG)
    3. None (no configuration applied)

    If a path is resolved and found, the configuration is loaded, validated,
    and applied. Relative file paths in the configuration (e.g., log filenames)
    are resolved relative to the YAML file's directory.

    WARNING: This function may close handlers previously configured by the
    host application. For integration into existing applications, configure
    the 'qreduce' logger hierarchy directly instead of calling this function.

    Args:
        config_path: Explicit path to the YAML configuration file.
        env_var: Environment variable name to check for the config path.

    Returns:
        The resolved Path that was used, or None if no configuration was applied.

    Raises:
        LoggingConfigError: If the configuration file cannot be read, parsed,
            or applied due to validation errors.
        FileNotFoundError: If an explicitly provided or environment-specified
            path does not exist.
    """
    resolved_path = _resolve_config_path(config_path, env_var)
    if resolved_path is None:
        return None

    config_dict = _load_yaml_config(resolved_path)
    _validate_config(config_dict, resolved_path)
    _resolve_handler_paths(config_dict, resolved_path.parent)
    _ensure_handler_directories(config_dict)
    _cleanup_managed_handlers()
    _apply_config(config_dict)
    return resolved_path


def get_default_config_path() -> Path | None:
    """Return the repository default logging configuration path, if found.

    Searches for config/logging.yaml relative to this module's package root.
    Returns None if the file does not exist (e.g., installed as a library).
    """
    # Module is at src/qreduce/logging_config.py, repo root is ../../
    package_root = Path(__file__).resolve().parent
    # When installed via pip, the package may not be in a src/ layout
    # Try finding config/ relative to the package location
    candidates = [
        package_root.parent.parent / "config" / "logging.yaml",  # src layout
        package_root.parent / "config" / "logging.yaml",  # flat layout
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _resolve_config_path(
    explicit_path: str | Path | None,
    env_var: str,
) -> Path | None:
    """Resolve the configuration path from explicit argument or environment."""
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"Logging configuration file not found: {path}"
            )
        return path.resolve()

    env_value = os.environ.get(env_var)
    if env_value:
        path = Path(env_value)
        if not path.is_file():
            raise FileNotFoundError(
                f"Logging configuration from {env_var} not found: {path}"
            )
        return path.resolve()

    return None


def _load_yaml_config(path: Path) -> dict:
    """Load and parse the YAML configuration file."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise LoggingConfigError(f"Cannot read logging configuration: {e}") from e

    try:
        config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise LoggingConfigError(
            f"Invalid YAML in logging configuration {path}: {e}"
        ) from e

    if config is None:
        raise LoggingConfigError(f"Empty logging configuration file: {path}")

    if not isinstance(config, dict):
        raise LoggingConfigError(
            f"Logging configuration must be a dictionary, got {type(config).__name__}: {path}"
        )

    return config


def _validate_config(config: dict, path: Path) -> None:
    """Validate the configuration structure for required fields."""
    if "version" not in config:
        raise LoggingConfigError(
            f"Logging configuration missing required 'version' key: {path}"
        )

    version = config["version"]
    if version != 1:
        raise LoggingConfigError(
            f"Unsupported logging configuration version {version} (expected 1): {path}"
        )

    # Validate handler configuration structure
    handlers = config.get("handlers", {})
    if not isinstance(handlers, dict):
        raise LoggingConfigError(
            f"'handlers' must be a dictionary: {path}"
        )

    for name, handler_config in handlers.items():
        if not isinstance(handler_config, dict):
            raise LoggingConfigError(
                f"Handler '{name}' configuration must be a dictionary: {path}"
            )
        if "class" not in handler_config:
            raise LoggingConfigError(
                f"Handler '{name}' missing required 'class' key: {path}"
            )

    # Validate logger configuration structure
    loggers = config.get("loggers", {})
    if not isinstance(loggers, dict):
        raise LoggingConfigError(
            f"'loggers' must be a dictionary: {path}"
        )


def _resolve_handler_paths(config: dict, yaml_dir: Path) -> None:
    """Resolve relative paths in handler configurations to absolute paths.

    File-based handlers (those with 'filename' key) have their paths resolved
    relative to the YAML configuration file's directory.
    """
    handlers = config.get("handlers", {})
    for handler_config in handlers.values():
        if not isinstance(handler_config, dict):
            continue
        if "filename" in handler_config:
            filename = handler_config["filename"]
            if isinstance(filename, str):
                file_path = Path(filename)
                if not file_path.is_absolute():
                    handler_config["filename"] = str(
                        (yaml_dir / file_path).resolve()
                    )


def _ensure_handler_directories(config: dict) -> None:
    """Create directories for file-based handlers if they don't exist."""
    handlers = config.get("handlers", {})
    for name, handler_config in handlers.items():
        if not isinstance(handler_config, dict):
            continue
        if "filename" in handler_config:
            filename = handler_config["filename"]
            if isinstance(filename, str):
                log_dir = Path(filename).parent
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    raise LoggingConfigError(
                        f"Cannot create log directory for handler '{name}': {e}"
                    ) from e


def _cleanup_managed_handlers() -> None:
    """Close and remove handlers from previous QReduce configuration.

    This prevents handler duplication when configure_logging is called multiple
    times (e.g., in tests or when reconfiguring).
    """
    qreduce_logger = logging.getLogger("qreduce")

    # Remove handlers we previously added
    for handler in _managed_handlers:
        try:
            handler.close()
        except Exception:  # noqa: BLE001, S110 - Best effort cleanup
            pass
        # Remove from qreduce logger and any child loggers
        if handler in qreduce_logger.handlers:
            qreduce_logger.handlers.remove(handler)

    _managed_handlers.clear()


def _apply_config(config: dict) -> None:
    """Apply the logging configuration using dictConfig."""
    try:
        logging.config.dictConfig(config)
    except (ValueError, TypeError, AttributeError) as e:
        raise LoggingConfigError(
            f"Failed to apply logging configuration: {e}"
        ) from e

    # Track handlers added to qreduce logger for future cleanup
    qreduce_logger = logging.getLogger("qreduce")
    _managed_handlers.extend(qreduce_logger.handlers)
