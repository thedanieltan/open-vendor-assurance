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

    ordered = sorted(sources, key=lambda s: (str(s.get("source_type") or ""), str(s.get("source_url") or "")))
    if ordered:
        rows = []
        for source in ordered:
            observed = _latest_observed_at(source)
            health = _source_health_label(source)
            rows.append(
                "<tr>"
                f"<td>{_esc(source.get('source_type'))}</td>"
                f'<td class="url"><a href="{_esc(source.get("source_url"))}" rel="nofollow noopener">{_esc(source.get("source_url"))}</a></td>'
                f"<td>{_esc(health) if health else f'<span class=\"muted\">{MISSING_SOURCE_HEALTH_LABEL}</span>'}</td>"
                f"<td>{_esc(observed) if observed else '<span class=\"muted\">—</span>'}</td>"
                "</tr>"
            )
        sources_html = (
            "<table><thead><tr>"
            "<th>Source type</th><th>Original vendor source URL</th>"
            "<th>Source health</th><th>Latest observation</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    else:
        sources_html = '<p class="muted">No public assurance sources are recorded yet.</p>'

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


def render_sitemap(config: PublicationConfig, vendor_ids: list[str], *, lastmod: str) -> str:
    urls = [config.canonical_base_url + "/", config.agents_url]
    urls.extend(config.vendor_page_url(vendor_id) for vendor_id in vendor_ids)
    entries = "".join(
        f"  <url>\n    <loc>{_esc(url)}</loc>\n    <lastmod>{_esc(lastmod)}</lastmod>\n  </url>\n"
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
    snapshot_date = generated_at[:10]
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
    _write(output_dir / "sitemap.xml", render_sitemap(config, vendor_ids, lastmod=snapshot_date))
    _write(output_dir / "llms.txt", render_llms_txt(config))

    manifest = discovery_manifest(config, commit_sha=commit_sha, generated_at=generated_at)
    _write(output_dir / ".well-known" / "openva.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {
        "vendor_pages": len(vendor_ids),
        "manifest_digest": manifest["snapshot"]["digest"],
    }
