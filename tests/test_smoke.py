"""Smoke tests: the console script exists and answers --help."""

from __future__ import annotations

import shutil
import subprocess

import pytest


def test_console_script_registered() -> None:
    assert shutil.which("data-gouv-cli"), "console script data-gouv-cli is not installed"


def test_help_starts() -> None:
    executable = shutil.which("data-gouv-cli")
    if executable is None:
        pytest.skip("console script not on PATH")
    result = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "help printed nothing"
