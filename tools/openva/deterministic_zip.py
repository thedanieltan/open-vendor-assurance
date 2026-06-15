"""Deterministic ZIP archive builder for immutable release bundles.

Reproducibility is the point: the same input tree and commit-derived timestamp
must produce a byte-identical archive (and therefore an identical SHA-256) on
every build. To get that, entries are written in sorted path order with a fixed
commit-derived timestamp, fixed permissions, a fixed creator system, and no
compression (so the bytes never depend on a host zlib version). Host filesystem
metadata (mtimes, owners) is never read into the archive.
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def _zip_date_time(generated_at: str) -> tuple[int, int, int, int, int, int]:
    text = generated_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    # ZIP timestamps have 2-second resolution and no timezone; normalize.
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second - dt.second % 2)


def build_deterministic_zip(
    source_dir: str | Path,
    archive_path: str | Path,
    *,
    arcname_root: str,
    generated_at: str,
) -> Path:
    source_dir = Path(source_dir)
    archive_path = Path(archive_path)
    date_time = _zip_date_time(generated_at)
    files = sorted(
        (path for path in source_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source_dir).as_posix(),
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # ZIP_STORED: no compression, so output bytes are independent of zlib.
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            rel = path.relative_to(source_dir).as_posix()
            arcname = f"{arcname_root}/{rel}" if arcname_root else rel
            info = zipfile.ZipInfo(arcname, date_time=date_time)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3  # fixed (unix) regardless of build host
            info.external_attr = (0o644 & 0xFFFF) << 16  # fixed regular-file perms
            archive.writestr(info, path.read_bytes())
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-deterministic-zip")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--arcname-root", default="")
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()
    build_deterministic_zip(
        args.source_dir, args.archive, arcname_root=args.arcname_root, generated_at=args.generated_at
    )
    print(f"Built {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
