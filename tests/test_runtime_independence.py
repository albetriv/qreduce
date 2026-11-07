"""Tests for import-time independence from optional backend bindings."""

import subprocess
import sys


def test_importing_qreduce_does_not_import_cplex() -> None:
    """The package root stays usable when CPLEX is absent."""

    completed_process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import qreduce; assert 'cplex' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed_process.returncode == 0, completed_process.stderr