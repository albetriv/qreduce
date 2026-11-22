"""Private Qreduce Pasqal credential profiles, not a Pasqal SDK format.

Credentials are deliberately never combined across sources. The profile file
is plaintext and must be protected by the user with appropriate filesystem ACLs.
"""

import os
from collections.abc import Mapping
from configparser import ConfigParser
from configparser import Error as ConfigError
from dataclasses import dataclass, field
from pathlib import Path


class PasqalCredentialsError(ValueError):
    """A credential source is missing, incomplete or malformed."""


@dataclass(frozen=True)
class PasqalCredentials:
    """Hold redacted Pasqal authentication fields."""

    username: str = field(repr=False)
    password: str = field(repr=False)
    project_id: str = field(repr=False)


def _validated(values: Mapping[str, object]) -> PasqalCredentials:
    keys = ("username", "password", "project_id")
    if any(not isinstance(values.get(key), str) or not values[key].strip() for key in keys):
        raise PasqalCredentialsError("Pasqal credential source is incomplete.")
    return PasqalCredentials(*(str(values[key]) for key in keys))


def resolve_pasqal_credentials(
    credentials: Mapping[str, object] | PasqalCredentials | None = None,
    *,
    profile: str = "default",
    environ: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> PasqalCredentials:
    """Resolve explicit credentials, environment, or a named profile, in order.

    A partially populated higher-priority source is an error, not a fallback.
    No credential values or file contents are included in diagnostics.
    """
    if credentials is not None:
        if isinstance(credentials, PasqalCredentials):
            return _validated(vars(credentials))
        return _validated(credentials)

    env = os.environ if environ is None else environ
    names = {"username": "PASQAL_USERNAME", "password": "PASQAL_PASSWORD", "project_id": "PASQAL_PROJECT_ID"}
    if any(name in env for name in names.values()):
        return _validated({key: env.get(name) for key, name in names.items()})

    file_path = Path.home() / ".qreduce" / "pasqal-credentials" if path is None else Path(path)
    parser = ConfigParser(interpolation=None)
    try:
        with file_path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        # Do not inherit credentials from INI DEFAULT or other profiles.
        if profile == parser.default_section or not parser.has_section(profile):
            raise PasqalCredentialsError("Pasqal credential profile is unavailable.")
        values = dict(parser._sections[profile])
    except (OSError, UnicodeError, ConfigError):
        raise PasqalCredentialsError("Pasqal credential file is unavailable or malformed.") from None
    return _validated(values)