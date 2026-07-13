import importlib.util
from pathlib import Path

_CONTRACT_PATH = Path(__file__).with_name("site_contract.py")
_SPEC = importlib.util.spec_from_file_location("openva_site_contract", _CONTRACT_PATH)
assert _SPEC and _SPEC.loader
_CONTRACT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONTRACT)

for _name, _value in vars(_CONTRACT).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


def test_release_workflow_builds_compiled_site_distribution():
    assert not (WORKFLOWS / "release-downloads.yml").exists()
    pages = (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8")
    assert "python site/build.py --out site/dist" in pages
    assert "actions/deploy-pages@v4" in pages


def test_site_docs_cover_compiled_distribution_and_public_boundaries():
    readme_text = (SITE / "README.md").read_text(encoding="utf-8")
    launch_text = (ROOT / "docs" / "public-launch-checklist.md").read_text(encoding="utf-8")
    text = readme_text + "\n" + launch_text

    for phrase in [
        "static OpenVA contract and community-index browser",
        "Static site",
        "Resolver contract documentation",
        "Community index browser",
        "Local resolver / CLI / MCP entry point",
        "Result-pack preview",
        "Configurable source-pack builder",
        "Browser-local resolver",
        "Source pack preview",
        "Export Source Pack",
        "compiled static distribution",
        "vendor-search.min.json",
        "data/vendors/{vendor_id}.json",
        "browser memory only",
        "not written to `localStorage`, `sessionStorage`, a server, or a database",
        "no backend, database, account system, upload endpoint",
        "no live verification job",
        "no live discovery job",
        "no hosted resolver worker",
        "community index is hint-only",
        "consumer-side live verification",
        "openva_{source_type}_candidate_basis",
        "openva_{source_type}_verification_basis",
        "no server-side workspace persistence",
        "public metadata",
    ]:
        assert phrase in text

    for phrase in [
        "Hosted site uses compiled/sharded catalog outputs",
        "Vendor detail records are generated",
        "Browser-local matcher still processes private inventories in memory only",
        "compiled catalog distribution",
    ]:
        assert phrase not in readme_text


# Phase 2 canonical one-page contract tests.
SITE_SRC = ROOT / "site" / "src"

SOURCE_LABELS = [
    "Data processing addendum",
    "Subprocessor list",
    "Privacy notice",
    "Trust center",
    "Security page",
    "Compliance page",
    "Certification reference",
    "Terms of service",
    "Know your customer statement",
    "Anti-money laundering statement",
    "Artificial intelligence terms",
    "Government request policy",
    "Transparency report",
    "Service status page",
    "Other public source",
]


def phase2_site_text() -> tuple[str, str, str]:
    return (
        (SITE_SRC / "index.html").read_text(encoding="utf-8"),
        (SITE_SRC / "styles.css").read_text(encoding="utf-8"),
        (SITE_SRC / "app.js").read_text(encoding="utf-8"),
    )


def test_canonical_site_is_one_page_catalog_first_and_lovable_independent():
    index, css, script = phase2_site_text()

    assert index.index('id="catalog-view"') < index.index('id="matcher-view"')
    assert index.index('id="matcher-view"') < index.index('id="export-view"')
    assert index.index('id="export-view"') < index.index('id="about-view"')
    assert 'href="#catalog"' in index
    assert 'href="#matcher"' in index
    assert 'href="#review"' in index
    assert 'href="#about"' in index
    assert "@lovable" not in index + css + script
    assert "Phase 2 canonical one-page design layer" in css
    assert "display: block !important" in css
    assert "onePageRoute" in script


def test_all_supported_source_types_use_full_human_labels():
    index, _, script = phase2_site_text()

    for label in SOURCE_LABELS:
        assert label in index
    assert 'data-source-pack-field="dpa"' in index
    assert "ALL_SOURCE_TYPES" in script
    assert "sourceTypeLabel(sourceType)" in script


def test_local_resolver_and_review_first_exports_are_present():
    index, _, script = phase2_site_text()

    for element_id in [
        "inventory-file",
        "run-local-match",
        "match-preview",
        "download-matches-xlsx",
        "download-matches-csv",
        "download-matches-json",
        "selection-summary",
        "download-xlsx",
        "download-vendors-csv",
        "download-sources-csv",
        "download-json",
    ]:
        assert f'id="{element_id}"' in index

    assert "browser memory" in index
    assert "Important notice before download" in index
    assert 'id="terms-disclaimer"' in index
    assert "Important Notice" in script
    assert "workbookBytes" in script
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in script


def test_public_page_has_no_vendor_completeness_badges_or_core_categories():
    index, css, script = phase2_site_text()
    text = "\n".join((index, css, script)).lower()
    for phrase in (
        "complete enough for review",
        "core complete",
        "scope complete",
        "partially complete",
        "core source",
    ):
        assert phrase not in text
