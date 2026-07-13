from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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


def test_canonical_site_is_one_page_catalog_first_and_lovable_independent():
    index = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    css = (SITE_SRC / "lovable-transplant.css").read_text(encoding="utf-8")
    script = (SITE_SRC / "openva-page.js").read_text(encoding="utf-8")

    assert index.index('id="catalog-view"') < index.index('id="matcher-view"')
    assert index.index('id="matcher-view"') < index.index('id="export-view"')
    assert index.index('id="export-view"') < index.index('id="about-view"')
    assert 'href="#catalog"' in index
    assert 'href="#matcher"' in index
    assert 'href="#review"' in index
    assert 'href="#about"' in index
    assert "Lovable runtime" not in index
    assert "@lovable" not in index + css + script
    assert "display: block !important" in css
    assert "onePageRoute" in script


def test_all_supported_source_types_use_full_human_labels():
    index = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    script = (SITE_SRC / "openva-page.js").read_text(encoding="utf-8")

    for label in SOURCE_LABELS:
        assert label in index
    assert 'data-source-pack-field="dpa"' in index
    assert "ALL_SOURCE_TYPES" in script
    assert "sourceTypeLabel(sourceType)" in script


def test_local_resolver_and_review_first_exports_are_present():
    index = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    script = (SITE_SRC / "openva-page.js").read_text(encoding="utf-8")

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
    text = "\n".join(
        (SITE_SRC / name).read_text(encoding="utf-8")
        for name in ("index.html", "lovable-transplant.css", "openva-page.js")
    ).lower()
    for phrase in (
        "complete enough for review",
        "core complete",
        "scope complete",
        "partially complete",
        "core source",
    ):
        assert phrase not in text
