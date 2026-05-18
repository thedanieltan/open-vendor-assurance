from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


def normalize_repo_path(path: Any) -> str:
    """Return a repository path with stable POSIX separators."""
    return PurePosixPath(str(path).strip().replace("\\", "/")).as_posix()


def relative_repo_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def display_path(path: Path, root: Path) -> str:
    try:
        return relative_repo_path(path.resolve(), root.resolve())
    except ValueError:
        return normalize_repo_path(path)
