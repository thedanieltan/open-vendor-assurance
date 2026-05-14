import subprocess
from pathlib import Path


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        text=True,
        capture_output=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_gitignore_covers_local_generated_artifacts():
    text = Path(".gitignore").read_text(encoding="utf-8")

    for pattern in [
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        ".pytest_cache/",
        "release-artifacts.json",
        "reports/",
    ]:
        assert pattern in text


def test_no_tracked_python_bytecode_files():
    forbidden = [path for path in tracked_files() if path.endswith((".pyc", ".pyo"))]

    assert forbidden == []


def test_no_tracked_pycache_paths():
    forbidden = [path for path in tracked_files() if "/__pycache__/" in path or path.startswith("__pycache__/")]

    assert forbidden == []
