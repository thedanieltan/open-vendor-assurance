"""Temporary binary isolation for PR #617; never merged."""

from __future__ import annotations

import subprocess
import sys


def test_enrichment_api_group() -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_openva_enrichment_api.py"],
        check=True,
    )
