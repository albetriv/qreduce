"""Smoke tests for the public package boundary."""

import qreduce


def test_package_exposes_version() -> None:
    """The installed package exposes its initial semantic version."""
    assert qreduce.__version__ == "0.1.0"