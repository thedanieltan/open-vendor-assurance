import dataclasses
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.publication import load_publication_config
from tools.openva.site_discovery import _latest_observed_at, render_index_html

ROOT = Path(__file__).resolve().parents[1]
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PAGES_BASE_URL = "https://thedanieltan.github.io/open-vendor-assurance"
INDEX_TEMPLATE = ROOT / "site" / "src" / "index.html"


class _HrefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.add(value)


def page_hrefs(page: str) -> set[str]:
    parser = _HrefCollector()
    parser.feed(page)
    return parser.hrefs


def build_site(out: Path) -> Path:
    # All std streams point at DEVNULL (always-valid OS handles) so Popen never
    # tries to duplicate the parent's or a tmp-filesystem handle, which is not
    # supported on every Windows mount.
    result = subprocess.run(
        [sys.executable, "site/build.py", "--out", str(out)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode == 0, f"site build failed (exit {result.returncode}) for {out}"
    return out


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    return build_site(tmp_path_factory.mktemp("disco-site"))


@pytest.fixture(scope="module")
def config():
    return load_publication_config()


def canonical_vendors() -> list[dict]:
    data = json.loads((ROOT / "indexes" / "vendor-search.json").read_text(encoding="utf-8"))
    return [row for row in data["items"] if row.get("vendor_id")]


def canonical_vendor_ids() -> list[str]:
    return sorted(row["vendor_id"] for row in canonical_vendors())


def sources_by_vendor() -> dict[str, list[str]]:
    data = json.loads((ROOT / "indexes" / "sources.json").read_text(encoding="utf-8"))
    index: dict[str, list[str]] = {}
    for row in data["items"]:
        if row.get("vendor_id") and row.get("source_url"):
            index.setdefault(row["vendor_id"], []).append(row["source_url"])
    return index


def sitemap_locs(site: Path) -> list[str]:
    tree = ET.parse(site / "sitemap.xml")
    return [el.text for el in tree.getroot().findall(".//sm:url/sm:loc", SITEMAP_NS)]


def test_every_canonical_vendor_has_exactly_one_static_page(site):
    expected = canonical_vendor_ids()
    pages = sorted(p.parent.name for p in site.glob("vendors/*/index.html"))
    assert pages == expected
    # Exactly one index.html per vendor directory, no stragglers.
    assert len(list(site.glob("vendors/*/index.html"))) == len(expected)
    assert len(list(site.glob("vendors/*/*"))) == len(expected)


def test_every_vendor_page_links_to_its_exact_json_export(site, config):
    for vendor_id in canonical_vendor_ids():
        page = (site / "vendors" / vendor_id / "index.html").read_text(encoding="utf-8")
        assert config.vendor_export_url(vendor_id) in page
        assert f"public/vendors/{vendor_id}.json" in page


def test_every_vendor_page_retains_original_source_urls(site):
    index = sources_by_vendor()
    for vendor_id, urls in index.items():
        page = (site / "vendors" / vendor_id / "index.html").read_text(encoding="utf-8")
        hrefs = page_hrefs(page)
        for url in urls:
            assert url in hrefs, f"{vendor_id} page missing source link {url}"


def test_sitemap_vendor_count_equals_canonical_vendor_count(site):
    locs = sitemap_locs(site)
    vendor_locs = [loc for loc in locs if "/vendors/" in loc]
    assert len(vendor_locs) == len(canonical_vendor_ids())


def test_sitemap_contains_every_vendor_page(site, config):
    locs = set(sitemap_locs(site))
    for vendor_id in canonical_vendor_ids():
        assert config.vendor_page_url(vendor_id) in locs
    # Homepage and the agent integration page are also present.
    assert config.canonical_base_url + "/" in locs
    assert config.agents_url in locs


def test_robots_references_the_sitemap(site, config):
    robots = (site / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {config.url('sitemap.xml')}" in robots
    assert "Allow: /" in robots


def test_well_known_manifest_points_to_root_agent_index(site, config):
    manifest = json.loads((site / ".well-known" / "openva.json").read_text(encoding="utf-8"))
    assert manifest["agent_index_url"] == config.agent_index_url
    assert manifest["agent_index_url"].endswith(config.agent_index_path)
    assert manifest["mcp"] == {"available": False, "manifest_url": None}
    assert manifest["not_advice"] is True


def test_generated_files_derive_from_publication_configuration(site, config):
    robots = (site / "robots.txt").read_text(encoding="utf-8")
    manifest = json.loads((site / ".well-known" / "openva.json").read_text(encoding="utf-8"))
    sample_page = (site / "vendors" / canonical_vendor_ids()[0] / "index.html").read_text(encoding="utf-8")

    assert config.canonical_base_url in robots
    assert config.canonical_base_url in sample_page
    assert manifest["canonical_base_url"] == config.canonical_base_url
    assert manifest["repository_url"] == config.repository_url
    assert "release_url" not in manifest
    meta = json.loads((site / "data" / "meta.json").read_text(encoding="utf-8"))
    assert "github_releases_url" not in meta
    assert meta["canonical_base_url"] == config.canonical_base_url


def test_generated_pages_contain_no_prohibited_advisory_claims(site):
    terms = yaml.safe_load((ROOT / "config" / "prohibited-claims.yaml").read_text(encoding="utf-8"))["prohibited_terms"]
    targets = list(site.glob("vendors/*/index.html")) + [
        site / "agents" / "index.html",
        site / "llms.txt",
        site / ".well-known" / "openva.json",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8").lower()
        for term in terms:
            term = term.lower()
            if " " in term or "-" in term:
                assert term not in text, f"{path.name} contains prohibited phrase {term!r}"
            else:
                # Whole-word match so legitimate substrings (e.g. security_page) do not trip.
                assert not re.search(rf"\b{re.escape(term)}\b", text), f"{path.name} contains prohibited term {term!r}"


def test_homepage_exposes_dataset_datacatalog_and_website_structured_data(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL)
    types = {json.loads(block)["@type"] for block in blocks}
    assert {"WebSite", "DataCatalog"}.issubset(types)
    catalog = next(json.loads(b) for b in blocks if json.loads(b)["@type"] == "DataCatalog")
    assert catalog["dataset"]["@type"] == "Dataset"


def test_generated_discovery_output_is_deterministic(tmp_path_factory):
    a = build_site(tmp_path_factory.mktemp("det-a"))
    b = build_site(tmp_path_factory.mktemp("det-b"))
    names = [
        "robots.txt",
        "sitemap.xml",
        "llms.txt",
        ".well-known/openva.json",
        "agents/index.html",
        "assets/openva-pages.css",
    ]
    names += [p.relative_to(a).as_posix() for p in sorted(a.glob("vendors/*/index.html"))]
    for name in names:
        assert (a / name).read_bytes() == (b / name).read_bytes(), f"non-deterministic: {name}"


def test_latest_observed_at_handles_missing_and_present_timestamps():
    assert _latest_observed_at({}) is None
    assert _latest_observed_at({"observed_at": "2026-07-01T10:00:00Z"}) == "2026-07-01T10:00:00Z"
    assert _latest_observed_at({"verified_at": "2026-07-02T10:00:00Z"}) == "2026-07-02T10:00:00Z"


def test_rendered_vendor_page_exposes_source_snapshot_language(config):
    html = render_index_html(
        title="Example",
        canonical_url=config.vendor_page_url("example"),
        description="Example vendor",
        body="<p>Example</p>",
        structured_data={"@context": "https://schema.org", "@type": "WebPage"},
    )
    assert "Snapshot" in html


def test_canonical_json_and_hash_helpers_are_stable():
    payload = {"b": 2, "a": 1}
    assert canonical_json(payload) == b'{"a":1,"b":2}'
    assert sha256_bytes(canonical_json(payload)) == sha256_bytes(b'{"a":1,"b":2}')


def test_config_is_dataclass(config):
    assert dataclasses.is_dataclass(config)
