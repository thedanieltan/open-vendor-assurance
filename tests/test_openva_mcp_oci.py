"""OCI image smoke test.

Builds the image and verifies a read-only mounted snapshot inside the
container. Skips with an explicit reason when Docker is unavailable; CI with a
Docker daemon runs it as the authoritative image-build check.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = "integrations/mcp/openva_mcp/Dockerfile"
IMAGE = "openva-mcp:pytest"

sys.path.insert(0, str(ROOT))

if shutil.which("docker") is None:
    pytest.skip("docker not available", allow_module_level=True)


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kwargs)


def test_oci_image_builds_and_verifies_a_snapshot(tmp_path):
    from tools.openva.agent_export import build_agent_exports

    snapshot = tmp_path / "snapshot"
    build_agent_exports(
        out_dir=snapshot,
        commit_sha="ocitest" + "0" * 33,
        generated_at="2026-06-15T00:00:00Z",
    )

    build = _run(["docker", "build", "-f", DOCKERFILE, "-t", IMAGE, "."])
    assert build.returncode == 0, build.stderr[-2000:]

    run = _run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "-v",
            f"{snapshot}:/snapshot:ro",
            IMAGE,
            "--snapshot",
            "/snapshot",
            "--verify",
        ]
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert "ok" in run.stderr.lower() or "ok" in run.stdout.lower()
