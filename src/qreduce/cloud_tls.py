"""Shared TLS trust configuration for cloud SDKs."""

import os
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

_CA_ENV_LOCK = RLock()


class CloudTLSConfigurationError(RuntimeError):
    """A local CA bundle could not be prepared safely."""


@contextmanager
def cloud_ca_environment(primary: str, *fallbacks: str) -> Iterator[None]:
    """Temporarily supply a combined CA bundle to an SDK via its environment.

    Keep the SDK's explicit bundle settings and default behavior when no Cato
    CA exists. Scope the automatic setting and bundle to the cloud operation.
    """
    # Serialize scopes that change process-wide environment, including nested callers.
    with _CA_ENV_LOCK:
        ca_path = Path.home() / ".cato" / "cato-ca.pem"
        if any(os.environ.get(name) for name in (primary, *fallbacks)) or not ca_path.exists():
            yield
            return

        from certifi import where

        with TemporaryDirectory(prefix="qreduce-ca-") as directory:
            bundle = Path(directory) / "combined-ca.pem"
            try:
                local_ca = ca_path.read_text(encoding="ascii")
                if "PRIVATE KEY-----" in local_ca:
                    raise ValueError("Expected certificates only.")
                ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=local_ca)
                roots = Path(where()).read_text(encoding="ascii")
                bundle.write_text(f"{roots.rstrip()}\n{local_ca.strip()}\n", encoding="ascii")
            except (OSError, ValueError) as error:
                raise CloudTLSConfigurationError("Unable to load the local Cato CA bundle.") from error

            previous = os.environ.get(primary)
            os.environ[primary] = str(bundle)
            try:
                yield
            finally:
                if previous is None:
                    os.environ.pop(primary, None)
                else:
                    os.environ[primary] = previous