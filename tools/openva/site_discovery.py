"""Static discovery surface for search engines and machine consumers.

Emits, into the built site tree, one static HTML page per canonical vendor plus
the cross-cutting discovery files: robots.txt, sitemap.xml, llms.txt, the
`.well-known/openva.json` manifest, and the agent integration page. Every
OpenVA-owned URL derives from `config/publication.yaml`; nothing here hardcodes
a base URL.

The output is a pure function of (compiled catalog, publication config,
commit_sha, generated_at). No wall-clock time is read, so two builds of the
same commit produce byte-identical discovery output. The manifest carries a
content digest over its own payload (excluding the snapshot block, matching the
agent export convention) so a consumer can detect drift.

These pages restate catalog facts only. They never imply OpenVA owns, endorses,
certifies, ranks, or represents a listed vendor, and they carry no advisory
wording.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.publication import PublicationConfig
from tools.openva.source_type_labels import source_type_labels

DISCOVERY_SCHEMA_VERSION = "1.0.0"
MISSING_SOURCE_HEALTH_LABEL = "No source-health observation"

PUBLIC_SOURCE_BOUNDARY = (
    "Only public, vendor-published sources are recorded. Gated, authenticated, "
    "or NDA-controlled materials are excluded and appear as access-state facts "
    "only."
)
NON_ADVISORY_BOUNDARY = (
    "OpenVA records public assurance source references as factual metadata. It "
    "does not endorse, certify, score, rank, or approve vendors, and nothing "
    "here is legal, compliance, procurement, security, or vendor-risk advice."
)

PAGE_STYLESHEET = """\
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #14181f;
  --muted: #5c6573;
  --line: #e2e6ec;
  --accent: #1f5fbf;
  --chip: #f1f4f9;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1217;
    --fg: #e7ebf2;
    --muted: #9aa4b2;
    --line: #232a34;
    --accent: #6aa3ff;
    --chip: #1a1f27;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 820px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
a { color: var(--accent); }
header.page-head { border-bottom: 1px solid var(--line); padding-bottom: 1.25rem; margin-bottom: 1.75rem; }
.eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; color: var(--muted); margin: 0 0 .35rem; }
h1 { font-size: 1.9rem; margin: 0 0 .5rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 .65rem; }
p { margin: 0 0 .9rem; }
.muted { color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: .4rem; margin: .25rem 0 0; padding: 0; list-style: none; }
.chips li { background: var(--chip); border: 1px solid var(--line); border-radius: 999px; padding: .15rem .7rem; font-size: .82rem; }
table { width: 100%; border-collapse: collapse; margin: .25rem 0 0; font-size: .92rem; }
th, td { text-align: left; vertical-align: top; padding: .55rem .5rem; border-bottom: 1px solid var(--line); }
th { font-size: .74rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
td.url { word-break: break-all; }
.boundary { border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.1rem; background: var(--chip); margin-top: 2rem; }
.boundary p { margin: 0 0 .6rem; font-size: .9rem; }
.boundary p:last-child { margin-bottom: 0; }
.meta-line { font-size: .82rem; color: var(--muted); }
footer.page-foot { margin-top: 2.5rem; padding-top: 1.25rem; border-top: 1px solid var(--line); font-size: .85rem; color: var(--muted); }
.links { display: flex; flex-wrap: wrap; gap: 1rem; margin: .25rem 0 0; padding: 0; list-style: none; }
code { background: var(--chip); border: 1px solid var(--line); border-radius: 6px; padding: .05rem .35rem; font-size: .85em; }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")


def _source_health_label(source: dict[str, Any]) -> str | None:
    health = source.get("source_health") or {}
    if health.get("status_bucket") in (None, "missing"):
        return None
    return str(health.get("label") or "").strip() or None


def _latest_observed_at(source: dict[str, Any]) -> str | None:
    verified = (source.get("source_health") or {}).get("verified_at")
    return str(verified) if verified else None


def _vendor_dataset_jsonld(config: PublicationConfig, vendor: dict[str, Any], export_url: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"{vendor.get('display_name')} — public assurance sources (OpenVA)",
        "description": (
            f"Public, vendor-published assurance source references recorded by "
            f"OpenVA for {vendor.get('display_name')}. Metadata only; not advice."
        ),
        "url": config.vendor_page_url(str(vendor.get("vendor_id"))),
        "isAccessibleForFree": True,
        "license": "https://opensource.org/license/mit",
        "creator": {"@type": "Organization", "name": config.project_name, "url": config.canonical_base_url},
        "isPartOf": {"@type": "DataCatalog", "name": config.project_name, "url": config.canonical_base_url},
        "distribution": {
            "@type": "DataDownload",
            "encodingFormat": "application/json",
            "contentUrl": export_url,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_vendor_page(
    config: PublicationConfig,
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    commit_sha: str,
    snapshot_date: str,
) -> str:
    vendor_id = str(vendor.get("vendor_id"))
    name = _esc(vendor.get("display_name"))
    canonical_url = config.vendor_page_url(vendor_id)
    export_url = config.vendor_export_url(vendor_id)

    domains = [d for d in (vendor.get("official_domains") or []) if d]
    domain_html = (
        '<ul class="chips">' + "".join(f"<li>{_esc(d)}</li>" for d in domains) + "</ul>"
        if domains
        else '<p class="muted">No official domains recorded.</p>'
    )

    # Every supported source type appears for every vendor: either the
    # vendor-published URL OpenVA currently records, or an explicit "no URL
    # currently recorded" row. Absence is a factual statement about OpenVA's
    # records, never a vendor risk or quality conclusion.
    labels = source_type_labels()
    by_type: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        by_type.setdefault(str(source.get("source_type") or ""), []).append(source)
    rows = []
    for source_type, label in labels.items():
        recorded = sorted(by_type.get(source_type, []), key=lambda s: str(s.get("source_url") or ""))
        if not recorded:
            rows.append(
                "<tr>"
                f"<td>{_esc(label)}</td>"
                '<td class="url"><span class="muted">No URL currently recorded</span></td>'
                '<td><span class="muted">—</span></td>'
                '<td><span class="muted">—</span></td>'
                "</tr>"
            )
            continue
        for source in recorded:
            observed = _latest_observed_at(source)
            health = _source_health_label(source)
            rows.append(
                "<tr>"
                f"<td>{_esc(label)}</td>"
                f'<td class="url"><a href="{_esc(source.get("source_url"))}" rel="nofollow noopener">{_esc(source.get("source_url"))}</a></td>'
                f"<td>{_esc(health) if health else f'<span class=\"muted\">{MISSING_SOURCE_HEALTH_LABEL}</span>'}</td>"
                f"<td>{_esc(observed) if observed else '<span class=\"muted\">—</span>'}</td>"
                "</tr>"
            )
    sources_html = (
        "<table><thead><tr>"
        "<th>Source type</th><th>Vendor-published source URL</th>"
        "<th>Source health</th><th>Last checked</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )

    jsonld = _vendor_dataset_jsonld(config, vendor, export_url)

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{name} — public assurance sources | {_esc(config.project_name)}</title>
    <meta name="description" content="Public, vendor-published assurance source references recorded by OpenVA for {name}. Metadata only; not advice.">
    <link rel="canonical" href="{_esc(canonical_url)}">
    <meta name="robots" content="index, follow">
    <link rel="stylesheet" href="../../assets/openva-pages.css">
    <script type="application/ld+json">
{jsonld}
    </script>
  </head>
  <body>
    <div class="wrap">
      <header class="page-head">
        <p class="eyebrow">OpenVA · Public vendor assurance sources</p>
        <h1>{name}</h1>
        <p class="muted">Vendor identifier <code>{_esc(vendor_id)}</code></p>
      </header>

      <h2>Official domains</h2>
      {domain_html}

      <h2>Public assurance sources</h2>
      {sources_html}

      <h2>Machine-readable export</h2>
      <p>The full source map for this vendor, with content digest and snapshot identity, is published as JSON:</p>
      <ul class="links">
        <li><a href="{_esc(export_url)}">Vendor JSON export</a></li>
        <li><a href="{_esc(config.agent_index_url)}">Agent index</a></li>
      </ul>

      <div class="boundary">
        <p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p>
        <p>{_esc(NON_ADVISORY_BOUNDARY)}</p>
      </div>

      <footer class="page-foot">
        <p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p>
        <ul class="links">
          <li><a href="../../">Catalog home</a></li>
          <li><a href="../../agents/">Agent integration</a></li>
        </ul>
      </footer>
    </div>
  </body>
</html>
"""


def render_agents_page(config: PublicationConfig, *, commit_sha: str, snapshot_date: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Agent &amp; machine integration | {_esc(config.project_name)}</title>
    <meta name="description" content="How AI agents and ingestion pipelines consume OpenVA: the agent index, per-vendor exports, snapshot pinning, digest verification, and source-citation rules.">
    <link rel="canonical" href="{_esc(config.agents_url)}">
    <meta name="robots" content="index, follow">
    <link rel="stylesheet" href="../assets/openva-pages.css">
  </head>
  <body>
    <div class="wrap">
      <header class="page-head">
        <p class="eyebrow">OpenVA · Integration</p>
        <h1>Agent &amp; machine integration</h1>
        <p class="muted">Static, read-only, digest-verifiable public exports for AI agents and ingestion pipelines.</p>
      </header>

      <h2>What is available</h2>
      <p>OpenVA publishes a public registry of vendor-published assurance source references as static JSON. Each record carries the source type, original vendor-published URL, observed source health where known, latest observation timestamp where known, and snapshot identity.</p>

      <h2>Where to start</h2>
      <ul class="links">
        <li><a href="{_esc(config.agent_index_url)}">Agent index</a></li>
        <li><a href="{_esc(config.vendor_index_url)}">Vendor index</a></li>
        <li><a href="{_esc(config.source_index_url)}">Source index</a></li>
        <li><a href="{_esc(config.url('.well-known/openva.json'))}">Discovery manifest</a></li>
      </ul>

      <h2>Pin and verify a snapshot</h2>
      <p>Every export carries a <code>snapshot</code> block (<code>commit_sha</code>, <code>generated_at</code>, <code>digest</code>). Pin a consumer to a <code>commit_sha</code> for reproducibility. To verify a file, remove its <code>snapshot</code> block, serialize the remainder as canonical JSON, and compare its SHA-256 digest.</p>

      <h2>Citing vendor sources</h2>
      <p>Always cite the original vendor-published source URL. OpenVA records the location and observed state of a public source; it does not host, mirror, or replace the vendor's own document.</p>

      <h2>Repository and contract</h2>
      <ul class="links">
        <li><a href="{_esc(config.repository_url)}">Repository</a></li>
        <li><a href="{_esc(config.export_contract_url)}">Export contract</a></li>
      </ul>

      <h2>MCP support</h2>
      <p>The discovery manifest reports current MCP availability. Static exports remain the baseline read-only integration surface.</p>

      <div class="boundary">
        <p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p>
        <p>{_esc(NON_ADVISORY_BOUNDARY)}</p>
      </div>

      <footer class="page-foot">
        <p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p>
        <ul class="links"><li><a href="../">Catalog home</a></li></ul>
      </footer>
    </div>
  </body>
</html>
"""


HOMEPAGE_PLACEHOLDERS = ("{{OPENVA_HOME_URL}}", "{{OPENVA_AGENT_INDEX_URL}}")


def render_index_html(template: str, config: PublicationConfig) -> str:
    return (
        template
        .replace("{{OPENVA_HOME_URL}}", config.url(""))
        .replace("{{OPENVA_AGENT_INDEX_URL}}", config.agent_index_url)
    )


def render_robots(config: PublicationConfig) -> str:
    return "User-agent: *\nAllow: /\n" f"Sitemap: {config.url('sitemap.xml')}\n"


def render_sitemap(config: PublicationConfig, vendor_ids: list[str], *, lastmod: str | None) -> str:
    urls = [config.canonical_base_url + "/", config.agents_url]
    urls.extend(config.vendor_page_url(vendor_id) for vendor_id in vendor_ids)
    lastmod_tag = f"    <lastmod>{_esc(lastmod)}</lastmod>\n" if lastmod else ""
    entries = "".join(
        f"  <url>\n    <loc>{_esc(url)}</loc>\n{lastmod_tag}  </url>\n"
        for url in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n"
    )


def render_llms_txt(config: PublicationConfig) -> str:
    return f"""# {config.project_name}

> Public, machine-readable registry of vendor-published assurance source
> references. Metadata only; not advice.

## Start here
- [Agent index]({config.agent_index_url}): root index of every export, with content digests
- [Vendor index]({config.vendor_index_url}): all catalogued vendors
- [Source index]({config.source_index_url}): flat list of public source references
- [Export contract]({config.export_contract_url}): export shapes and digest verification
- [Source repository]({config.repository_url}): current accepted catalog and history

## Rules for consumers
- Pin an exact commit SHA or verified digest when a fixed state is required.
- Always cite the original vendor-published source URL recorded on each source.
- OpenVA makes no compliance, suitability, security, or risk determination about any vendor.

This file is a convenience pointer, not an authority or integrity mechanism.
Verify snapshots with the digests in the agent index.
"""


def discovery_manifest(config: PublicationConfig, *, commit_sha: str, generated_at: str) -> dict[str, Any]:
    payload = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project": config.project_name,
        "canonical_base_url": config.canonical_base_url,
        "repository_url": config.repository_url,
        "agent_index_url": config.agent_index_url,
        "vendor_index_url": config.vendor_index_url,
        "source_index_url": config.source_index_url,
        "export_contract_url": config.export_contract_url,
        "publication_model": "continuous_main",
        "mcp": {"available": False, "manifest_url": None},
        "not_advice": True,
    }
    digest = sha256_bytes(canonical_json(payload))
    payload["snapshot"] = {
        "commit_sha": commit_sha,
        "generated_at": generated_at,
        "digest": digest,
    }
    return payload


def build_discovery(
    output_dir: Path,
    config: PublicationConfig,
    *,
    vendor_summaries: list[dict[str, Any]],
    vendor_details: dict[str, dict[str, Any]],
    commit_sha: str,
    generated_at: str,
) -> dict[str, Any]:
    # A missing snapshot timestamp stays an explicit unavailable state; it is
    # never rendered as an epoch (January 1, 1970) date.
    trimmed = generated_at.strip()
    lastmod = trimmed[:10] if trimmed and not trimmed.startswith("1970-01-01") else None
    snapshot_date = lastmod or "date unavailable"
    _write(output_dir / "assets" / "openva-pages.css", PAGE_STYLESHEET)

    vendor_ids: list[str] = []
    for vendor in sorted(vendor_summaries, key=lambda v: str(v.get("vendor_id") or "")):
        vendor_id = str(vendor.get("vendor_id") or "")
        if not vendor_id:
            continue
        vendor_ids.append(vendor_id)
        detail = vendor_details.get(vendor_id, {})
        page = render_vendor_page(
            config,
            vendor,
            detail.get("canonical_sources", []),
            commit_sha=commit_sha,
            snapshot_date=snapshot_date,
        )
        _write(output_dir / "vendors" / vendor_id / "index.html", page)

    _write(output_dir / "agents" / "index.html", render_agents_page(config, commit_sha=commit_sha, snapshot_date=snapshot_date))
    _write(output_dir / "robots.txt", render_robots(config))
    _write(output_dir / "sitemap.xml", render_sitemap(config, vendor_ids, lastmod=lastmod))
    _write(output_dir / "llms.txt", render_llms_txt(config))

    manifest = discovery_manifest(config, commit_sha=commit_sha, generated_at=generated_at)
    _write(output_dir / ".well-known" / "openva.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {
        "vendor_pages": len(vendor_ids),
        "manifest_digest": manifest["snapshot"]["digest"],
    }



# Phase 3 SEO, answer-engine, and generative-engine discovery surface.
SOURCE_TYPE_DESCRIPTIONS = {
    "dpa": "A public vendor-published agreement or addendum describing data-processing terms.",
    "subprocessors_list": "A public vendor-published list of subprocessors, affiliates, or service providers used to process data.",
    "privacy_notice": "A public notice explaining how the vendor collects, uses, shares, or protects personal information.",
    "trust_center": "A public trust or assurance portal describing the vendor's security, privacy, compliance, or resilience programme.",
    "security_page": "A public page describing the vendor's security practices, controls, or security programme.",
    "compliance_page": "A public page describing standards, frameworks, attestations, or compliance-related information.",
    "certification_reference": "A public vendor-published reference to a certification, attestation, or independent assurance instrument.",
    "terms_of_service": "Public terms governing access to or use of the vendor's products, services, or websites.",
    "kyc_statement": "A public statement about know-your-customer practices or requirements.",
    "aml_statement": "A public statement about anti-money-laundering practices or requirements.",
    "ai_terms": "Public terms, notices, or policies addressing artificial-intelligence features, training, inputs, or outputs.",
    "government_request_policy": "A public policy describing how the vendor handles government or law-enforcement requests.",
    "transparency_report": "A public report describing government requests, content actions, or other transparency metrics.",
    "status_page": "A public service-status page reporting availability, incidents, or maintenance.",
    "other_public_source": "Another public vendor or authority source that does not fit the more specific supported source types.",
}


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    import struct
    import zlib

    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def _social_preview_png() -> bytes:
    import struct
    import zlib

    width, height = 1200, 630
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            if 70 < x < 250 and 165 < y < 345:
                pixel = (232, 246, 238)
            elif 96 < x < 224 and 191 < y < 319:
                pixel = (23, 107, 80)
            elif x > 760 and y < 250:
                pixel = (27, 116, 86)
            else:
                shade = int(248 - (y / height) * 13)
                pixel = (shade, min(250, shade + 2), max(238, shade - 4))
            raw.extend((*pixel, 255))
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _png_chunk(b"IEND", b"")


def _favicon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="16" fill="#176b50"/>
  <path d="M15 18h10l7 25 7-25h10L37 50H27z" fill="#fff"/>
</svg>"""


def _breadcrumb_jsonld(config: PublicationConfig, items: list[tuple[str, str]]) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": index, "name": name, "item": url}
            for index, (name, url) in enumerate(items, start=1)
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _vendor_dataset_jsonld(config: PublicationConfig, vendor: dict[str, Any], export_url: str) -> str:
    vendor_id = str(vendor.get("vendor_id"))
    page_url = config.vendor_page_url(vendor_id)
    payload = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": f"{page_url}#dataset",
        "name": f"{vendor.get('display_name')} public vendor assurance sources",
        "description": f"Public vendor-published assurance source references recorded by OpenVA for {vendor.get('display_name')}.",
        "url": page_url,
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "creator": {"@id": f"{config.url('')}#organization"},
        "isPartOf": {"@id": f"{config.url('')}#catalog"},
        "distribution": {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": export_url},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_vendor_page(
    config: PublicationConfig,
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    commit_sha: str,
    snapshot_date: str,
) -> str:
    vendor_id = str(vendor.get("vendor_id"))
    raw_name = str(vendor.get("display_name") or vendor_id)
    name = _esc(raw_name)
    canonical_url = config.vendor_page_url(vendor_id)
    export_url = config.vendor_export_url(vendor_id)
    image_url = config.url("assets/openva-social-preview.png")
    labels = source_type_labels()
    domains = [d for d in (vendor.get("official_domains") or []) if d]
    domain_html = '<ul class="chips">' + "".join(f"<li>{_esc(d)}</li>" for d in domains) + "</ul>" if domains else '<p class="muted">No official domains recorded.</p>'

    by_type: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        by_type.setdefault(str(source.get("source_type") or ""), []).append(source)
    recorded_types = [label for source_type, label in labels.items() if by_type.get(source_type)]
    recorded_count = sum(len(rows) for rows in by_type.values())
    missing_count = sum(1 for source_type in labels if not by_type.get(source_type))
    rows: list[str] = []
    for source_type, label in labels.items():
        directory_url = config.url(f"source-types/{source_type}/")
        recorded = sorted(by_type.get(source_type, []), key=lambda row: str(row.get("source_url") or ""))
        if not recorded:
            rows.append(
                "<tr>"
                f'<td><a href="{_esc(directory_url)}">{_esc(label)}</a></td>'
                '<td class="url"><span class="muted">No URL currently recorded</span></td>'
                '<td><span class="muted">—</span></td><td><span class="muted">—</span></td></tr>'
            )
            continue
        for source in recorded:
            observed = _latest_observed_at(source)
            health = _source_health_label(source)
            rows.append(
                "<tr>"
                f'<td><a href="{_esc(directory_url)}">{_esc(label)}</a></td>'
                f'<td class="url"><a href="{_esc(source.get("source_url"))}" rel="nofollow noopener">{_esc(source.get("source_url"))}</a></td>'
                f"<td>{_esc(health) if health else f'<span class=\"muted\">{MISSING_SOURCE_HEALTH_LABEL}</span>'}</td>"
                f"<td>{_esc(observed) if observed else '<span class=\"muted\">—</span>'}</td></tr>"
            )
    sources_html = "<table><thead><tr><th>Source type</th><th>Vendor-published source URL</th><th>Source health</th><th>Last checked</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    dataset = _vendor_dataset_jsonld(config, vendor, export_url)
    breadcrumb = _breadcrumb_jsonld(config, [("OpenVA", config.url("")), (raw_name, canonical_url)])
    listed = ", ".join(recorded_types[:4]) if recorded_types else "public vendor assurance sources"
    description = f"Find {raw_name}'s public {listed} and related vendor assurance source URLs recorded by OpenVA."
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{name} public privacy, security and assurance sources | OpenVA</title>
    <meta name="description" content="{_esc(description)}">
    <link rel="canonical" href="{_esc(canonical_url)}"><meta name="robots" content="index, follow">
    <meta property="og:type" content="website"><meta property="og:site_name" content="OpenVA">
    <meta property="og:title" content="{name} public vendor assurance sources | OpenVA">
    <meta property="og:description" content="{_esc(description)}"><meta property="og:url" content="{_esc(canonical_url)}">
    <meta property="og:image" content="{_esc(image_url)}"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{_esc(image_url)}">
    <link rel="icon" type="image/svg+xml" href="../../assets/openva-favicon.svg"><link rel="stylesheet" href="../../assets/openva-pages.css">
    <script type="application/ld+json">{dataset}</script>
    <script type="application/ld+json">{breadcrumb}</script>
  </head>
  <body><div class="wrap">
    <header class="page-head"><p class="eyebrow">OpenVA · Public vendor assurance sources</p><h1>{name}</h1><p class="muted">Vendor identifier <code>{_esc(vendor_id)}</code></p></header>
    <h2>What public sources does OpenVA record for {name}?</h2>
    <p>OpenVA currently records <strong>{recorded_count}</strong> public source URL(s) for this vendor. Across the fifteen supported source types, <strong>{missing_count}</strong> type(s) currently have no URL recorded. Absence is not a vendor risk or quality conclusion.</p>
    <h2>Official domains</h2>{domain_html}
    <h2>Public assurance sources</h2>{sources_html}
    <h2>Machine-readable export</h2><p>The source map, snapshot identity, and content digest are available as JSON.</p>
    <ul class="links"><li><a href="{_esc(export_url)}">Vendor JSON export</a></li><li><a href="{_esc(config.agent_index_url)}">Agent index</a></li><li><a href="{_esc(config.url('source-types/'))}">Source-type directory</a></li></ul>
    <div class="boundary"><p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p><p>{_esc(NON_ADVISORY_BOUNDARY)}</p></div>
    <footer class="page-foot"><p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p><ul class="links"><li><a href="../../">Catalog home</a></li><li><a href="../../agents/">Agent integration</a></li></ul></footer>
  </div></body>
</html>"""


def render_source_type_page(
    config: PublicationConfig,
    source_type: str,
    label: str,
    vendors: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    commit_sha: str,
    snapshot_date: str,
) -> str:
    page_url = config.url(f"source-types/{source_type}/")
    image_url = config.url("assets/openva-social-preview.png")
    rows: list[str] = []
    source_total = 0
    for vendor, sources in vendors:
        vendor_id = str(vendor.get("vendor_id"))
        source_total += len(sources)
        links = "<br>".join(
            f'<a href="{_esc(source.get("source_url"))}" rel="nofollow noopener">{_esc(source.get("source_url"))}</a>'
            for source in sources
        )
        rows.append(f'<tr><td><a href="../../vendors/{_esc(vendor_id)}/">{_esc(vendor.get("display_name"))}</a></td><td class="url">{links}</td></tr>')
    records = "<table><thead><tr><th>Vendor</th><th>Vendor-published source URL</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>" if rows else '<p class="muted">No accepted URL is currently recorded for this source type.</p>'
    description = SOURCE_TYPE_DESCRIPTIONS.get(source_type, "A supported public vendor assurance source type.")
    breadcrumb = _breadcrumb_jsonld(config, [("OpenVA", config.url("")), ("Source types", config.url("source-types/")), (label, page_url)])
    collection = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage", "@id": f"{page_url}#page",
        "name": f"{label} directory | OpenVA", "description": description, "url": page_url,
        "isPartOf": {"@id": f"{config.url('')}#website"},
    }, indent=2, sort_keys=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(label)} directory | OpenVA</title><meta name="description" content="Find public vendor-published {_esc(label.lower())} URLs recorded by OpenVA.">
<link rel="canonical" href="{_esc(page_url)}"><meta name="robots" content="index, follow">
<meta property="og:type" content="website"><meta property="og:site_name" content="OpenVA"><meta property="og:title" content="{_esc(label)} directory | OpenVA"><meta property="og:url" content="{_esc(page_url)}"><meta property="og:image" content="{_esc(image_url)}">
<link rel="icon" type="image/svg+xml" href="../../assets/openva-favicon.svg"><link rel="stylesheet" href="../../assets/openva-pages.css">
<script type="application/ld+json">{collection}</script><script type="application/ld+json">{breadcrumb}</script></head>
<body><div class="wrap"><header class="page-head"><p class="eyebrow">OpenVA · Source-type directory</p><h1>{_esc(label)}</h1><p class="muted">Machine key <code>{_esc(source_type)}</code></p></header>
<h2>What is this source type?</h2><p>{_esc(description)}</p>
<h2>What does OpenVA currently record?</h2><p><strong>{len(vendors)}</strong> vendor(s) and <strong>{source_total}</strong> accepted public URL(s) are currently recorded for this source type.</p>{records}
<div class="boundary"><p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p><p>{_esc(NON_ADVISORY_BOUNDARY)}</p></div>
<footer class="page-foot"><p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p><ul class="links"><li><a href="../">All source types</a></li><li><a href="../../">Catalog home</a></li></ul></footer>
</div></body></html>"""


def render_source_type_index_page(config: PublicationConfig, counts: dict[str, tuple[int, int]], *, commit_sha: str, snapshot_date: str) -> str:
    labels = source_type_labels()
    rows = "".join(
        f'<tr><td><a href="{_esc(source_type)}/">{_esc(label)}</a></td><td>{counts.get(source_type, (0, 0))[0]}</td><td>{counts.get(source_type, (0, 0))[1]}</td></tr>'
        for source_type, label in labels.items()
    )
    page_url = config.url("source-types/")
    breadcrumb = _breadcrumb_jsonld(config, [("OpenVA", config.url("")), ("Source types", page_url)])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Supported public source types | OpenVA</title><meta name="description" content="Definitions and current catalog counts for the fifteen public vendor assurance source types supported by OpenVA."><link rel="canonical" href="{_esc(page_url)}"><meta name="robots" content="index, follow"><link rel="icon" type="image/svg+xml" href="../assets/openva-favicon.svg"><link rel="stylesheet" href="../assets/openva-pages.css"><script type="application/ld+json">{breadcrumb}</script></head>
<body><div class="wrap"><header class="page-head"><p class="eyebrow">OpenVA · Vocabulary</p><h1>Supported public source types</h1><p class="muted">Fifteen compatibility-stable machine keys with full human-facing labels.</p></header>
<p>Each page defines one source type and lists the vendor-published URLs currently recorded. A zero count means no accepted URL is currently recorded; it is not a vendor assessment.</p>
<table><thead><tr><th>Source type</th><th>Vendors</th><th>URLs</th></tr></thead><tbody>{rows}</tbody></table>
<div class="boundary"><p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p><p>{_esc(NON_ADVISORY_BOUNDARY)}</p></div><footer class="page-foot"><p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p><a href="../">Catalog home</a></footer></div></body></html>"""


def render_agents_page(config: PublicationConfig, *, commit_sha: str, snapshot_date: str) -> str:
    labels = source_type_labels()
    vocabulary = "".join(f"<li><code>{_esc(key)}</code> — {_esc(label)}</li>" for key, label in labels.items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent and machine integration | {_esc(config.project_name)}</title><meta name="description" content="Citation-ready OpenVA exports, stable source-type vocabulary, snapshot pinning, digest verification, and vendor-source citation rules."><link rel="canonical" href="{_esc(config.agents_url)}"><meta name="robots" content="index, follow"><link rel="icon" type="image/svg+xml" href="../assets/openva-favicon.svg"><link rel="stylesheet" href="../assets/openva-pages.css"></head>
<body><div class="wrap"><header class="page-head"><p class="eyebrow">OpenVA · Integration</p><h1>Agent &amp; machine integration</h1><p class="muted">Static, read-only, digest-verifiable public exports for agents and ingestion pipelines.</p></header>
<h2>What is OpenVA?</h2><p>OpenVA is a public registry of vendor-published assurance source URLs. It provides locator metadata and provenance; it does not replace or interpret the vendor's document.</p>
<h2>Where should a consumer start?</h2><ul class="links"><li><a href="{_esc(config.agent_index_url)}">Agent index</a></li><li><a href="{_esc(config.vendor_index_url)}">Vendor index</a></li><li><a href="{_esc(config.source_index_url)}">Source index</a></li><li><a href="{_esc(config.url('source-types/'))}">Source-type directory</a></li><li><a href="{_esc(config.url('.well-known/openva.json'))}">Discovery manifest</a></li></ul>
<h2>How should a result be cited?</h2><p>Cite the original vendor-published URL as the authority for vendor content. Cite the OpenVA vendor page or JSON export for the catalog snapshot, source classification, provenance, and observation state.</p>
<h2>How is a snapshot verified?</h2><p>Pin an exact <code>commit_sha</code> or verified digest. Remove the export's <code>snapshot</code> block, serialize the remaining payload as canonical JSON, and compare its SHA-256 digest.</p>
<h2>Supported source-type vocabulary</h2><ul>{vocabulary}</ul>
<h2>Repository and contract</h2><ul class="links"><li><a href="{_esc(config.repository_url)}">Repository</a></li><li><a href="{_esc(config.export_contract_url)}">Export contract</a></li><li><a href="{_esc(config.url('llms.txt'))}">Machine guidance</a></li></ul>
<div class="boundary"><p>{_esc(PUBLIC_SOURCE_BOUNDARY)}</p><p>{_esc(NON_ADVISORY_BOUNDARY)}</p></div><footer class="page-foot"><p class="meta-line">Snapshot {_esc(commit_sha)} · {_esc(snapshot_date)}</p><a href="../">Catalog home</a></footer></div></body></html>"""


def render_index_html(template: str, config: PublicationConfig) -> str:
    return (template.replace("{{OPENVA_HOME_URL}}", config.url(""))
            .replace("{{OPENVA_AGENT_INDEX_URL}}", config.agent_index_url)
            .replace("{{OPENVA_REPOSITORY_URL}}", config.repository_url))


def _render_urlset(urls: list[str], *, lastmod: str | None) -> str:
    lastmod_tag = f"    <lastmod>{_esc(lastmod)}</lastmod>\n" if lastmod else ""
    entries = "".join(f"  <url>\n    <loc>{_esc(url)}</loc>\n{lastmod_tag}  </url>\n" for url in urls)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + entries + "</urlset>\n"


def render_sitemap(config: PublicationConfig, vendor_ids: list[str], *, lastmod: str | None, source_types: list[str] | None = None) -> str:
    source_types = source_types or []
    urls = [config.url(""), config.agents_url, config.url("source-types/")]
    urls.extend(config.vendor_page_url(vendor_id) for vendor_id in vendor_ids)
    urls.extend(config.url(f"source-types/{source_type}/") for source_type in source_types)
    return _render_urlset(urls, lastmod=lastmod)


def render_llms_txt(config: PublicationConfig, *, vendor_count: int = 0, source_count: int = 0, generated_at: str = "") -> str:
    vocabulary = "\n".join(f"- `{key}`: {label}" for key, label in source_type_labels().items())
    return f"""# {config.project_name}

> Public, machine-readable registry of vendor-published assurance source URLs.
> Locator metadata and provenance only; not advice or a substitute for vendor content.

## Current catalog
- Accepted vendors: {vendor_count}
- Accepted public source records: {source_count}
- Snapshot generated at: {generated_at or 'unavailable'}

## Start here
- [Agent index]({config.agent_index_url}): root index of exports and content digests
- [Vendor index]({config.vendor_index_url}): accepted vendors
- [Source index]({config.source_index_url}): accepted public source references
- [Source-type directory]({config.url('source-types/')}): definitions and current vendor/URL counts
- [Discovery manifest]({config.url('.well-known/openva.json')}): machine endpoints and snapshot identity
- [Export contract]({config.export_contract_url}): shapes and digest verification
- [Source repository]({config.repository_url}): accepted catalog history

## Citation rules
- Cite the original vendor-published URL for claims about vendor content.
- Cite an OpenVA vendor page or JSON export for source classification, provenance, observation state, and snapshot identity.
- Pin an exact commit SHA or verified digest when a fixed catalog state is required.
- A missing URL means only that OpenVA currently records no accepted URL for that vendor and source type.

## Supported source types
{vocabulary}

## Boundaries
- OpenVA does not approve, certify, endorse, rank, recommend, or assess vendors.
- OpenVA does not provide legal, compliance, procurement, security, privacy, or risk advice.
- Vendor URLs can move; consult the current resolved URL and observation timestamp where available.

This file is a convenience map. The agent index and per-export digests are the integrity mechanisms.
"""


def discovery_manifest(
    config: PublicationConfig,
    *,
    commit_sha: str,
    generated_at: str,
    vendor_count: int = 0,
    source_count: int = 0,
) -> dict[str, Any]:
    labels = source_type_labels()
    payload = {
        "schema_version": "1.1.0",
        "project": config.project_name,
        "canonical_base_url": config.canonical_base_url,
        "repository_url": config.repository_url,
        "agent_index_url": config.agent_index_url,
        "vendor_index_url": config.vendor_index_url,
        "source_index_url": config.source_index_url,
        "source_type_index_url": config.url("source-types/"),
        "export_contract_url": config.export_contract_url,
        "sitemaps": {
            "all": config.url("sitemap.xml"),
            "pages": config.url("sitemap-pages.xml"),
            "vendors": config.url("sitemap-vendors.xml"),
            "source_types": config.url("sitemap-source-types.xml"),
        },
        "catalog": {"vendor_count": vendor_count, "source_count": source_count, "source_type_count": len(labels)},
        "source_type_vocabulary": labels,
        "citation_policy": {
            "vendor_content_authority": "original_vendor_published_url",
            "catalog_metadata_authority": "openva_snapshot_and_export",
            "missing_url_meaning": "no_accepted_url_currently_recorded",
        },
        "publication_model": "continuous_main",
        "mcp": {"available": False, "manifest_url": None},
        "not_advice": True,
    }
    digest = sha256_bytes(canonical_json(payload))
    payload["snapshot"] = {"commit_sha": commit_sha, "generated_at": generated_at, "digest": digest}
    return payload


def build_discovery(
    output_dir: Path,
    config: PublicationConfig,
    *,
    vendor_summaries: list[dict[str, Any]],
    vendor_details: dict[str, dict[str, Any]],
    commit_sha: str,
    generated_at: str,
) -> dict[str, Any]:
    trimmed = generated_at.strip()
    lastmod = trimmed[:10] if trimmed and not trimmed.startswith("1970-01-01") else None
    snapshot_date = lastmod or "date unavailable"
    labels = source_type_labels()
    _write(output_dir / "assets" / "openva-pages.css", PAGE_STYLESHEET)
    _write(output_dir / "assets" / "openva-favicon.svg", _favicon_svg())
    _write_bytes(output_dir / "assets" / "openva-social-preview.png", _social_preview_png())
    _write(output_dir / "site.webmanifest", json.dumps({
        "name": "Open Vendor Assurance", "short_name": "OpenVA", "start_url": "./", "display": "standalone",
        "background_color": "#f7f7f4", "theme_color": "#176b50",
        "icons": [{"src": "assets/openva-favicon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }, indent=2, sort_keys=True) + "\n")

    vendor_ids: list[str] = []
    source_type_vendors: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = {key: [] for key in labels}
    source_count = 0
    for vendor in sorted(vendor_summaries, key=lambda row: str(row.get("vendor_id") or "")):
        vendor_id = str(vendor.get("vendor_id") or "")
        if not vendor_id:
            continue
        vendor_ids.append(vendor_id)
        detail = vendor_details.get(vendor_id, {})
        sources = list(detail.get("canonical_sources", []))
        source_count += len(sources)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            grouped.setdefault(str(source.get("source_type") or ""), []).append(source)
        for source_type in labels:
            if grouped.get(source_type):
                source_type_vendors[source_type].append((vendor, grouped[source_type]))
        _write(output_dir / "vendors" / vendor_id / "index.html", render_vendor_page(
            config, vendor, sources, commit_sha=commit_sha, snapshot_date=snapshot_date
        ))

    counts = {key: (len(rows), sum(len(sources) for _, sources in rows)) for key, rows in source_type_vendors.items()}
    _write(output_dir / "source-types" / "index.html", render_source_type_index_page(config, counts, commit_sha=commit_sha, snapshot_date=snapshot_date))
    for source_type, label in labels.items():
        _write(output_dir / "source-types" / source_type / "index.html", render_source_type_page(
            config, source_type, label, source_type_vendors[source_type], commit_sha=commit_sha, snapshot_date=snapshot_date
        ))

    _write(output_dir / "agents" / "index.html", render_agents_page(config, commit_sha=commit_sha, snapshot_date=snapshot_date))
    _write(output_dir / "robots.txt", render_robots(config))
    _write(output_dir / "sitemap.xml", render_sitemap(config, vendor_ids, lastmod=lastmod, source_types=list(labels)))
    _write(output_dir / "sitemap-pages.xml", _render_urlset([config.url(""), config.agents_url, config.url("source-types/")], lastmod=lastmod))
    _write(output_dir / "sitemap-vendors.xml", _render_urlset([config.vendor_page_url(vendor_id) for vendor_id in vendor_ids], lastmod=lastmod))
    _write(output_dir / "sitemap-source-types.xml", _render_urlset([config.url(f"source-types/{key}/") for key in labels], lastmod=lastmod))
    _write(output_dir / "llms.txt", render_llms_txt(config, vendor_count=len(vendor_ids), source_count=source_count, generated_at=generated_at))

    manifest = discovery_manifest(config, commit_sha=commit_sha, generated_at=generated_at, vendor_count=len(vendor_ids), source_count=source_count)
    _write(output_dir / ".well-known" / "openva.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "vendor_pages": len(vendor_ids),
        "source_type_pages": len(labels),
        "manifest_digest": manifest["snapshot"]["digest"],
    }
