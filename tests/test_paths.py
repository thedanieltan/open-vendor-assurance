from pathlib import PurePosixPath, PureWindowsPath

from tools.openva.paths import normalize_repo_path


def test_normalize_windows_repo_path():
    path = PureWindowsPath("data") / "vendors" / "example" / "vendor.yaml"

    assert normalize_repo_path(path) == "data/vendors/example/vendor.yaml"


def test_normalize_linux_repo_path():
    path = PurePosixPath("data") / "vendors" / "example" / "sources" / "example-dpa.yaml"

    assert normalize_repo_path(path) == "data/vendors/example/sources/example-dpa.yaml"


def test_normalize_ios_style_container_path():
    path = (
        "/private/var/mobile/Containers/Data/Application/OPENVA/Documents/"
        "data/vendors/example/vendor.yaml"
    )

    assert (
        normalize_repo_path(path)
        == "/private/var/mobile/Containers/Data/Application/OPENVA/Documents/data/vendors/example/vendor.yaml"
    )


def test_normalize_mixed_separators():
    path = "catalog-batches\\regional/apac-saas.yaml"

    assert normalize_repo_path(path) == "catalog-batches/regional/apac-saas.yaml"
