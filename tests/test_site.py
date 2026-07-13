import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

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


def resolver_site_build_module():
    spec = importlib.util.spec_from_file_location(
        "openva_site_build_browser_test",
        SITE / "build.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compiled_catalog_publishes_only_bounded_registration_match_keys():
    compiled = resolver_site_build_module().build_compiled_catalog()
    vendors = {row["vendor_id"]: row for row in compiled["vendor_summaries"]}
    assert vendors["adobe"]["registration_keys"] == [
        {
            "jurisdiction": "US",
            "legal_name": "Adobe Inc.",
            "registration_number": "0000796343",
        }
    ]
    assert vendors["atlassian"]["registration_keys"]
    allowed = {"registration_number", "jurisdiction", "legal_name"}
    for vendor in vendors.values():
        for key in vendor["registration_keys"]:
            assert set(key) == allowed
            assert "_openva_path" not in key
            assert "verification_source_ids" not in key
            assert "notes" not in key


def test_static_site_vendor_index_contains_registration_match_keys(tmp_path: Path):
    module = resolver_site_build_module()
    output = tmp_path / "site-dist"
    module.build_site(output)
    payload = json.loads(
        (output / "data" / "vendor-search.min.json").read_text(encoding="utf-8")
    )
    vendors = {row["vendor_id"]: row for row in payload["items"]}
    assert payload["meta"]["vendor_count"] == len(vendors)
    assert vendors["adobe"]["registration_keys"][0]["registration_number"] == "0000796343"


def test_browser_resolver_source_carries_explicit_fail_closed_contract():
    source = (SITE_SRC / "ui-fixes.js").read_text(encoding="utf-8")
    required_tokens = {
        'company: "vendor_name"',
        'website: "domain"',
        'uen: "registration_number"',
        'method: "domain_subdomain"',
        'method: "registration_number_exact"',
        'status: "ambiguous"',
        '"openva_match_status"',
        '"openva_match_note"',
        "No supported identity column was found",
        "No inventory data was uploaded",
    }
    for token in required_tokens:
        assert token in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_browser_resolver_javascript_executes_matching_contract(tmp_path: Path):
    source = (SITE_SRC / "ui-fixes.js").read_text(encoding="utf-8")
    marker = "\n})();\n"
    assert source.endswith(marker)
    exports = """
  globalThis.__openvaResolverTest = {
    parseInventoryCsv,
    normalizeDomainValue,
    buildResolverIndexes,
    matchingDecision,
  };
"""
    instrumented = source[: -len(marker)] + exports + marker
    harness = r'''
const vm = require("node:vm");
const assert = require("node:assert/strict");
const context = {
  console,
  URL,
  addEventListener: () => {},
  setTimeout: () => 0,
  clearTimeout: () => {},
  localStorage: { getItem: () => null, setItem: () => {} },
  document: {
    documentElement: { dataset: {}, removeAttribute: () => {} },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener: () => {},
    head: { appendChild: () => {} },
    createElement: () => ({
      addEventListener: () => {},
      append: () => {},
      appendChild: () => {},
      classList: { add: () => {} },
      dataset: {},
      setAttribute: () => {},
    }),
  },
  catalogData: {
    vendors: [
      {
        vendor_id: "adobe",
        display_name: "Adobe",
        legal_name: "Adobe Inc.",
        official_domains: ["adobe.com"],
        registration_keys: [{
          registration_number: "0000796343",
          jurisdiction: "US",
          legal_name: "Adobe Inc.",
        }],
      },
      {
        vendor_id: "atlassian",
        display_name: "Atlassian",
        legal_name: "Atlassian Pty Ltd",
        official_domains: ["atlassian.com"],
        registration_keys: [{
          registration_number: "53102443916",
          jurisdiction: "AU",
          legal_name: "Atlassian Pty Ltd",
        }],
      },
    ],
  },
};
context.window = context;
context.globalThis = context;
vm.runInNewContext(__SOURCE__, context, { filename: "ui-fixes.js" });
const resolver = context.__openvaResolverTest;
const parsed = resolver.parseInventoryCsv(
  "Company;Website;UEN;Country\nAdobe;https://security.adobe.com/path;0000796343;US\n"
);
assert.equal(parsed.length, 1);
assert.equal(parsed[0].vendor_name, "Adobe");
assert.equal(parsed[0].domain, "https://security.adobe.com/path");
assert.equal(parsed[0].registration_number, "0000796343");
assert.equal(parsed[0].jurisdiction, "US");
const indexes = resolver.buildResolverIndexes();
let decision = resolver.matchingDecision({ domain: "https://security.adobe.com/path" }, indexes);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "adobe");
assert.equal(decision.method, "domain_subdomain");
decision = resolver.matchingDecision({ business_entity_name: "Adobe Incorporated" }, indexes);
assert.equal(decision.status, "no_match");
decision = resolver.matchingDecision({ business_entity_name: "Adobe Inc." }, indexes);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "adobe");
assert.equal(decision.method, "name_exact");
decision = resolver.matchingDecision(
  { registration_number: "53 102 443 916", jurisdiction: "AU" }, indexes
);
assert.equal(decision.status, "matched");
assert.equal(decision.vendor.vendor_id, "atlassian");
assert.equal(decision.method, "registration_number_exact");
decision = resolver.matchingDecision(
  { domain: "adobe.com", registration_number: "53102443916", jurisdiction: "AU" }, indexes
);
assert.equal(decision.status, "ambiguous");
assert.equal(decision.vendor, null);
'''.replace("__SOURCE__", json.dumps(instrumented))
    script = tmp_path / "browser-resolver-contract.cjs"
    script.write_text(harness, encoding="utf-8")
    completed = subprocess.run(
        [shutil.which("node") or "node", str(script)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_vendor_detail_slide_preserves_references_and_hides_redundant_fields(tmp_path: Path):
    module = resolver_site_build_module()
    output = tmp_path / "site-dist"
    module.build_site(output)
    compiled_index = (output / "index.html").read_text(encoding="utf-8")
    renderer = (output / "public-vendor-detail.js").read_text(encoding="utf-8")
    assert 'public-vendor-detail.js?v=20260713-vendor-detail' in compiled_index
    assert 'PUBLIC_VENDOR_DETAIL_VERSION = "references-only-v1"' in renderer
    assert '<tr><th>Source type</th><th>Reference</th><th>Export</th></tr>' in renderer
    assert 'href="${html(source.source_url)}"' in renderer
    assert 'target="_blank"' in renderer
    for forbidden in [
        "source-health",
        "last checked",
        "candidate sources",
        "unavailable notes",
        "Related observation events",
        "Assurance Intelligence",
        "provenance.collected_at",
        "source_authority_class",
        "access_class",
        "rights_class",
        "review_state",
    ]:
        assert forbidden not in renderer


def test_catalog_navigation_is_loaded_after_vendor_detail(tmp_path: Path):
    output = tmp_path / "site-dist"
    resolver_site_build_module().build_site(output)
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


def test_catalog_navigation_bounds_rendered_results_and_bulk_selection():
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
    ]:
        assert token in script


def test_catalog_navigation_provides_accessible_mobile_drawer_and_url_state():
    script = (SITE_SRC / "catalog-navigation.js").read_text(encoding="utf-8")
    for token in [
        "catalog-detail-drawer",
        "Back to results",
        'panel.setAttribute("role", "dialog")',
        'panel.setAttribute("aria-modal", "true")',
        'event.key === "Escape"',
        'params.set("page", String(currentPage))',
        'params.set("vendor", activeVendorId)',
        "window.history.pushState",
        'window.addEventListener("popstate"',
    ]:
        assert token in script


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
