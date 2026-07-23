"""The shared JS matcher core reproduces the Python core's normalization contract.

WP-OPENVA-LIVE-RESOLVER-BOUNDARY-01.

Runs the Node conformance harness (site/test/resolver-conformance.cjs), which executes the
single shared JS matcher core (site/src/openva-matcher-core.js) against the committed vectors
generated from the authoritative Python core. This is the cross-runtime lock: a normalization
change on either side fails closed here. Skips only when Node is unavailable (the harness still
runs in CI, which has Node).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "site" / "test" / "resolver-conformance.cjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_shared_js_core_reproduces_python_normalization_contract():
    completed = subprocess.run(
        [shutil.which("node") or "node", str(HARNESS)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
