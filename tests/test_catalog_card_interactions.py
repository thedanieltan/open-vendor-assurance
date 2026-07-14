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
        "openva_site_build_catalog_card_test",
        SITE / "build.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiled_site_loads_responsive_card_layer_after_catalog_navigation(tmp_path: Path):
    output = tmp_path / "site-dist"
    site_build_module().build_site(output)
    index = (output / "index.html").read_text(encoding="utf-8")

    assert (output / "catalog-card-interactions.js").is_file()
    assert index.index("catalog-navigation.js?v=20260714-pagination-drawer") < index.index(
        "catalog-card-interactions.js?v=20260715-responsive-card-sheet"
    )
    assert index.index("catalog-card-interactions.js?v=20260715-responsive-card-sheet") < index.index(
        "ui-fixes.js?v=20260713-phase2"
    )


def test_vendor_cards_replace_checkbox_tapping_with_whole_card_selection():
    source = (SITE_SRC / "catalog-card-interactions.js").read_text(encoding="utf-8")
    for token in [
        '.vendor-card > label {',
        'display: none !important;',
        '.vendor-card h4 button::after',
        'position: absolute;',
        'inset: 0;',
        'checkbox.checked = !checkbox.checked;',
        'checkbox.dispatchEvent(new Event("change", { bubbles: true }))',
        'button.setAttribute("aria-pressed", String(selected))',
        'state.textContent = selected ? "Selected" : "Select";',
    ]:
        assert token in source


def test_mobile_vendor_links_use_bounded_sliding_sheet_without_page_overflow():
    source = (SITE_SRC / "catalog-card-interactions.js").read_text(encoding="utf-8")
    for token in [
        'overflow-x: clip !important;',
        '.catalog-detail-scrim',
        'body.catalog-drawer-open .catalog-detail-scrim',
        '@keyframes openva-catalog-sheet-in',
        'transform: translateX(100%);',
        'width: min(94dvw, 34rem) !important;',
        'max-width: 100dvw !important;',
        'overflow-x: hidden !important;',
        'className = "vendor-reference-list";',
        'className = "vendor-reference-card";',
        'wrapper.replaceWith(list);',
    ]:
        assert token in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_catalog_card_interactions_javascript_parses():
    completed = subprocess.run(
        [
            shutil.which("node") or "node",
            "--check",
            str(SITE_SRC / "catalog-card-interactions.js"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
