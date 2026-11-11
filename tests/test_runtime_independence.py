"""Tests for import-time independence from optional backend bindings."""

import subprocess
import sys


def test_importing_qreduce_does_not_import_optional_solver_bindings() -> None:
    """The package root stays usable when optional classical and Ocean bindings are absent."""

    completed_process = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import qreduce; "
                "assert 'cplex' not in sys.modules; "
                "assert 'pyscipopt' not in sys.modules; "
                "assert 'dimod' not in sys.modules; "
                "assert 'dwave.samplers' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed_process.returncode == 0, completed_process.stderr