"""Tests for scoped cloud TLS configuration."""

import os
from pathlib import Path

import pytest

from qreduce.cloud_tls import CloudTLSConfigurationError, cloud_ca_environment


@pytest.fixture
def local_ca(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "AWS_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".cato" / "cato-ca.pem"
    path.parent.mkdir()
    return path


def test_missing_local_ca_keeps_sdk_defaults(local_ca):
    with cloud_ca_environment("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        assert "REQUESTS_CA_BUNDLE" not in os.environ


@pytest.mark.parametrize("variable", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_explicit_bundle_has_priority(local_ca, monkeypatch, variable):
    local_ca.write_text("invalid CA", encoding="ascii")
    monkeypatch.setenv(variable, "explicit.pem")
    with cloud_ca_environment("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        assert os.environ[variable] == "explicit.pem"
        assert os.environ.get("REQUESTS_CA_BUNDLE") == (
            "explicit.pem" if variable == "REQUESTS_CA_BUNDLE" else None
        )


def test_invalid_local_ca_fails_before_sdk_call(local_ca):
    pytest.importorskip("certifi")
    local_ca.write_text("invalid CA", encoding="ascii")
    with (
        pytest.raises(CloudTLSConfigurationError, match="Unable to load the local Cato CA"),
        cloud_ca_environment("REQUESTS_CA_BUNDLE"),
    ):
        pytest.fail("Should not proceed to SDK")
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_combined_bundle_and_environment_restored_on_error(local_ca, monkeypatch):
    certifi = pytest.importorskip("certifi")
    roots = Path(certifi.where()).read_text(encoding="ascii")
    anchor = roots[roots.index("-----BEGIN CERTIFICATE-----"):].split("-----END CERTIFICATE-----", 1)[0]
    anchor += "-----END CERTIFICATE-----\n"
    local_ca.write_text(anchor, encoding="ascii")
    monkeypatch.setenv("AWS_CA_BUNDLE", "")

    with pytest.raises(RuntimeError, match="SDK failure"), cloud_ca_environment("AWS_CA_BUNDLE"):
        bundle = Path(os.environ["AWS_CA_BUNDLE"])
        assert bundle.read_text(encoding="ascii") == roots.rstrip() + "\n" + anchor
        assert "REQUESTS_CA_BUNDLE" not in os.environ
        raise RuntimeError("SDK failure")

    assert not bundle.exists()
    assert os.environ["AWS_CA_BUNDLE"] == ""