from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "data/vendors/acuity-scheduling/sources/acuity-scheduling-dpa.yaml",
    "data/vendors/acuity-scheduling/sources/acuity-scheduling-privacy.yaml",
    "data/vendors/acuity-scheduling/sources/acuity-scheduling-security.yaml",
    "data/vendors/acuity-scheduling/sources/acuity-scheduling-status-page.yaml",
    "data/vendors/acuity-scheduling/sources/acuity-scheduling-terms-of-service.yaml",
)


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    source_path_file = Path("/tmp/openva-acuity-source-paths.txt")
    verification_report = Path("/tmp/openva-acuity-verification.json")
    observation_dir = Path("/tmp/openva-acuity-observations")

    source_path_file.write_text("\n".join(SOURCE_PATHS) + "\n", encoding="utf-8")

    run(
        sys.executable,
        "-m",
        "tools.openva.source_verification",
        "verify",
        "--source-path-file",
        str(source_path_file),
        "--output",
        str(verification_report),
    )
    run(
        sys.executable,
        "-m",
        "tools.openva.observation_ledger",
        "build",
        "--verification-report",
        str(verification_report),
        "--output-dir",
        str(observation_dir),
        "--run-id",
        "owner-acuity-squarespace-source-repair-rebased",
        "--baseline",
        "maintenance/source-observations/latest-observations.json",
    )
    run(
        sys.executable,
        "-m",
        "tools.openva.observation_ledger",
        "install-latest",
        "--latest",
        str(observation_dir / "latest-observations.json"),
    )
    run(sys.executable, "-m", "tools.openva.validate", "build-indexes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
