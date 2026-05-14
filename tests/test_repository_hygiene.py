from pathlib import Path


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
    forbidden = list(Path(".").glob("**/*.pyc")) + list(Path(".").glob("**/*.pyo"))

    assert forbidden == []


def test_no_tracked_pycache_directories_with_files():
    cache_files = [path for path in Path(".").glob("**/__pycache__/*") if path.is_file()]

    assert cache_files == []
