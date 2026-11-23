"""Credential resolution uses fake values and never contacts the provider."""

from pathlib import Path

import pytest

from qreduce.solving.mwis.pasqal_credentials import (
    PasqalCredentials,
    PasqalCredentialsError,
    resolve_pasqal_credentials,
)


def test_default_path_uses_pasqual_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".qreduce" / "pasqal-credentials"
    legacy.parent.mkdir()
    legacy.write_text("[default]\nusername=legacy\npassword=fake\nproject_id=legacy-project\n")

    with pytest.raises(PasqalCredentialsError):
        resolve_pasqal_credentials(environ={})

    path = tmp_path / ".pasqual" / "credentials"
    path.parent.mkdir()
    path.write_text("[default]\nusername=file\npassword=fake\nproject_id=file-project\n")
    assert resolve_pasqal_credentials(environ={}).username == "file"


def test_precedence_and_no_secret_repr(tmp_path):
    path = tmp_path / "credentials"
    path.write_text("[default]\nusername=file\npassword=file-secret\nproject_id=file-project\n")
    env = {"PASQAL_USERNAME": "env", "PASQAL_PASSWORD": "env-secret", "PASQAL_PROJECT_ID": "env-project"}
    explicit = {"username": "api", "password": "api-secret", "project_id": "api-project"}
    result = resolve_pasqal_credentials(explicit, environ=env, path=path)
    assert result.username == "api"
    assert "api-secret" not in repr(result)
    assert resolve_pasqal_credentials(environ=env, path=path).username == "env"
    assert resolve_pasqal_credentials(environ={}, path=path).username == "file"


def test_partial_sources_do_not_fall_back(tmp_path):
    path = tmp_path / "credentials"
    path.write_text("[default]\nusername=file\npassword=file-secret\nproject_id=file-project\n")
    for explicit, env in [({}, {}), (None, {"PASQAL_USERNAME": "fake-secret"})]:
        with pytest.raises(PasqalCredentialsError) as error:
            resolve_pasqal_credentials(explicit, environ=env, path=path)
        assert "fake-secret" not in str(error.value)


def test_profile_isolation_and_malformed_files(tmp_path):
    path = tmp_path / "credentials"
    path.write_text("[DEFAULT]\npassword=secret\n[research]\nusername=user\nproject_id=project\n")
    with pytest.raises(PasqalCredentialsError):
        resolve_pasqal_credentials(profile="research", environ={}, path=path)
    path.write_text("[bad\nfake-secret")
    with pytest.raises(PasqalCredentialsError) as error:
        resolve_pasqal_credentials(environ={}, path=path)
    assert "fake-secret" not in str(error.value)


def test_explicit_dataclass_is_validated():
    with pytest.raises(PasqalCredentialsError):
        resolve_pasqal_credentials(PasqalCredentials("user", "", "project"))