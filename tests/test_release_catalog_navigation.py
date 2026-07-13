import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_SRC = SITE / "src"


def site_build_module():
    spec = importlib.util.spec_from_file_location(
        "openva_site_build_catalog_navigation_test",
        SITE / "build.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiled_site_loads_catalog_navigation_after_vendor_detail(tmp_path: Path):
    output = tmp_path / "site-dist"
    site_build_module().build_site(output)

    index = (output / "index.html").read_text(encoding="utf-8")
    assert (output / "catalog-navigation.js").is_file()
    assert index.index("app.js?v=20260713-phase2") < index.index(
        "public-vendor-detail.js?v=20260713-vendor-detail"
    )
    assert index.index("public-vendor-detail.js?v=20260713-vendor-detail") < index.index(
        "catalog-navigation.js?v=20260714-pagination-drawer"
    )
    assert index.index("catalog-navigation.js?v=20260714-pagination-drawer") < index.index(
        "ui-fixes.js?v=20260713-phase2"
    )


def test_catalog_navigation_bounds_results_and_preserves_selection_contract():
    script = (SITE_SRC / "catalog-navigation.js").read_text(encoding="utf-8")

    for token in [
        'const DESKTOP_PAGE_SIZE = 25;',
        'const COMPACT_PAGE_SIZE = 10;',
        "visibleVendors.slice(start, start + size)",
        'id = "catalog-page-status"',
        'id = "catalog-pagination"',
        'pageButton.textContent = `Select this page (${currentPageVendors.length})`',
        'allButton.textContent = `Select all filtered (${visibleVendors.length})`',
        "selectedVendors.add(vendor.vendor_id)",
        "selectedSources",
    ]:
        assert token in script


def test_catalog_navigation_provides_mobile_drawer_and_url_state():
    script = (SITE_SRC / "catalog-navigation.js").read_text(encoding="utf-8")

    for token in [
        "catalog-detail-drawer",
        "Back to results",
        'panel.setAttribute("role", "dialog")',
        'panel.setAttribute("aria-modal", "true")',
        'event.key === "Escape"',
        'params.set("page", String(currentPage))',
        'params.set("vendor", activeVendorId)',
        'window.history.pushState',
        'window.addEventListener("popstate"',
    ]:
        assert token in script


def test_existing_vendor_reference_links_remain_the_detail_surface():
    script = (SITE_SRC / "public-vendor-detail.js").read_text(encoding="utf-8")

    assert '<th>Source type</th><th>Reference</th><th>Export</th>' in script
    assert 'href="${html(source.source_url)}"' in script
    assert 'data-select-source="${html(source.source_id)}"' in script


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_catalog_navigation_javascript_parses():
    completed = subprocess.run(
        [shutil.which("node") or "node", "--check", str(SITE_SRC / "catalog-navigation.js")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
