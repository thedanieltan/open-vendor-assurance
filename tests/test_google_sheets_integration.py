"""Temporary binary isolation for PR #617; never merged."""

from __future__ import annotations

import subprocess
import sys


def test_enrichment_note_contract() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_openva_enrichment_api.py::test_enrich_source_type_selection_and_missing_types_are_null",
        ],
        check=True,
    )
