"""Portable contract tests for the static Sharpe run catalog."""

import json

from qreduce.artifacts.metadata import sha256_hex
from qreduce.experiments.portfolio_sr.run_catalog import main, write_catalog


def _run(root, name, *, experiment="sharpe_portfolio", schema="1.1", rounds=(), text=""):
    directory = root / name
    directory.mkdir()
    files = {
        "config_used.json": {"reduction": {"max_reduction_rounds": 0}},
        "experiment_metadata.json": {"description": text},
        "problem.json": {"tickers": ["A"]},
        "run_result.json": {"status": "completed"},
        **{f"round_{index:02d}_result.json": {"round_index": index} for index in rounds},
    }
    for filename, value in files.items():
        (directory / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "artifact_schema_version": schema,
        "experiment_id": experiment,
        "run_id": name,
        "created_at": "2025-01-01T00:00:00Z",
        "files": {filename: sha256_hex(value) for filename, value in files.items()},
    }
    (directory / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _catalog(path):
    content = path.read_text(encoding="ascii")
    prefix = "window.QReduceRunCatalogSR = "
    assert content.startswith(prefix) and content.endswith(";\n")
    return json.loads(content[len(prefix):-2])


def test_catalog_indexes_supported_runs_and_preserves_artifact_text(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    first = _run(root, "a_baseline", schema="1.0")
    second = _run(root, "b_reduced", rounds=(0, 2))
    _run(root, "other", experiment="portfolio_mv")
    (root / ".hidden").mkdir()
    (root / "not_a_run.txt").write_text("ignored", encoding="utf-8")
    destination = tmp_path / "nested" / "catalog.js"

    assert write_catalog(root, destination) == (2, [])
    entries = _catalog(destination)
    assert [entry["id"] for entry in entries] == ["a_baseline", "b_reduced"]
    for entry, directory in zip(entries, (first, second)):
        expected = {p.name for p in directory.glob("*.json")}
        assert set(entry["files"]) == expected
        for name, text in entry["files"].items():
            assert text == (directory / name).read_text(encoding="utf-8")
            json.loads(text)


def test_invalid_runs_are_skipped_without_blocking_valid_runs(tmp_path):
    _run(tmp_path, "valid")
    corrupt = _run(tmp_path, "corrupt")
    (corrupt / "problem.json").write_text('{"changed": true}', encoding="utf-8")
    missing = _run(tmp_path, "missing")
    (missing / "run_result.json").unlink()
    mismatch = _run(tmp_path, "mismatch")
    manifest_path = mismatch / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "different"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _run(tmp_path, "unsupported", schema="99")

    destination = tmp_path / "catalog.js"
    count, skipped = write_catalog(tmp_path, destination)
    assert count == 1
    assert [entry["id"] for entry in _catalog(destination)] == ["valid"]
    assert {message.split(":", 1)[0] for message in skipped} == {
        "corrupt", "missing", "mismatch", "unsupported"
    }
    assert any("hash mismatch" in message.lower() for message in skipped)
    assert any("run_id" in message for message in skipped)


def test_serialization_keeps_untrusted_text_as_data(tmp_path):
    payload = '"; window.injected = true; //\n\\ café \u2028'
    directory = _run(tmp_path, "safe", text=payload)
    destination = tmp_path / "catalog.js"
    assert write_catalog(tmp_path, destination) == (1, [])
    content = destination.read_text(encoding="ascii")
    assert "\\u00e9" in content and "\\u2028" in content
    entries = _catalog(destination)
    artifact = entries[0]["files"]["experiment_metadata.json"]
    assert artifact == (directory / "experiment_metadata.json").read_text(encoding="utf-8")
    assert json.loads(artifact)["description"] == payload


def test_cli_reports_skips_and_missing_root(tmp_path, capsys):
    root = tmp_path / "runs"
    root.mkdir()
    _run(root, "ok")
    (root / "broken").mkdir()
    destination = tmp_path / "catalog.js"
    assert main(["--output-root", str(root), "--catalog", str(destination)]) == 0
    output = capsys.readouterr()
    assert "1 run(s) indexed" in output.out
    assert "Skipped broken:" in output.err
    assert main(["--output-root", str(tmp_path / "absent"), "--catalog", str(destination)]) == 1
    assert "Cannot update UIX catalog" in capsys.readouterr().err
    assert [entry["id"] for entry in _catalog(destination)] == ["ok"]