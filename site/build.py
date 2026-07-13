"""Continuous-publication wrapper for the compiled site builder.

The implementation is preserved byte-for-byte in ``site/build_core.py``. This
wrapper removes the retired formal-release metadata, makes the exact source
commit the sole catalog snapshot identity, adds the bounded public identity
keys required by the browser resolver, and keeps human vendor pages focused on
usable public references rather than maintenance telemetry.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.openva import site_discovery as _SITE_DISCOVERY

_CORE_PATH = Path(__file__).with_name("build_core.py")
_SPEC = importlib.util.spec_from_file_location("openva_site_build_core", _CORE_PATH)
assert _SPEC and _SPEC.loader
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)

for _name, _value in vars(_CORE).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

_ORIGINAL_BUILD_META = _CORE.build_meta
_ORIGINAL_BUILD_COMPILED_CATALOG = _CORE.build_compiled_catalog
_ORIGINAL_RENDER_INDEX_HTML = _CORE.render_index_html
_ORIGINAL_RENDER_VENDOR_PAGE = _SITE_DISCOVERY.render_vendor_page


def release_tag() -> str:
    """Formal catalog release tags are not part of OpenVA publication."""
    return ""


def build_meta(pack: dict[str, Any], sources: list[dict[str, Any]], vendor_count: int) -> dict[str, Any]:
    meta = _ORIGINAL_BUILD_META(pack, sources, vendor_count)
    meta.pop("release_tag", None)
    meta.pop("github_releases_url", None)
    meta["catalog_snapshot_identity"] = meta.get("commit_sha") or "unknown"
    meta["publication_model"] = "continuous_main"
    return meta


def _public_registration_keys() -> dict[str, list[dict[str, str]]]:
    """Return canonical public registration keys grouped by vendor.

    The browser resolver receives only the identity fields needed for matching.
    Internal paths, evidence references, notes, and lifecycle metadata remain out
    of the lightweight vendor-search payload.
    """
    path = ROOT / "indexes" / "legal-entities.json"
    if not path.is_file():
        return {}

    payload = load_json(path)
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in payload.get("items", []):
        if not isinstance(row, dict) or row.get("catalog_status") != "canonical":
            continue
        vendor_id = str(row.get("vendor_id") or "").strip()
        registration_number = str(row.get("registration_number") or "").strip()
        if not vendor_id or not registration_number:
            continue
        grouped.setdefault(vendor_id, []).append(
            {
                "registration_number": registration_number,
                "jurisdiction": str(row.get("jurisdiction") or "").strip(),
                "legal_name": str(row.get("legal_name") or "").strip(),
            }
        )

    return {
        vendor_id: sorted(
            rows,
            key=lambda row: (
                row["jurisdiction"],
                row["registration_number"],
                row["legal_name"],
            ),
        )
        for vendor_id, rows in grouped.items()
    }


def build_compiled_catalog(
    source_health_snapshot_path: Path = DEFAULT_SOURCE_HEALTH_SNAPSHOT,
    assurance_intelligence_snapshot_path: Path = DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT,
) -> dict[str, Any]:
    compiled = _ORIGINAL_BUILD_COMPILED_CATALOG(
        source_health_snapshot_path,
        assurance_intelligence_snapshot_path,
    )
    registration_keys = _public_registration_keys()
    for summary in compiled["vendor_summaries"]:
        vendor_id = str(summary.get("vendor_id") or "")
        summary["registration_keys"] = registration_keys.get(vendor_id, [])
    return compiled


def render_index_html(template: str, config: Any) -> str:
    """Load the focused human vendor-detail renderer after the legacy runtime."""
    page = _ORIGINAL_RENDER_INDEX_HTML(template, config)
    marker = '    <script src="ui-fixes.js?v=20260713-phase2"></script>'
    replacement = (
        '    <script src="public-vendor-detail.js?v=20260713-vendor-detail"></script>\n'
        + marker
    )
    if marker not in page:
        raise ValueError("could not locate the homepage script insertion point")
    return page.replace(marker, replacement, 1)


def _public_source_table(sources: list[dict[str, Any]]) -> str:
    """Render only the human-useful source type, title and external URL."""
    labels = _SITE_DISCOVERY.source_type_labels()
    rows = []
    recorded = [source for source in sources if str(source.get("source_url") or "").strip()]
    recorded.sort(
        key=lambda source: (
            labels.get(str(source.get("source_type") or ""), str(source.get("source_type") or "")),
            str(source.get("title") or ""),
            str(source.get("source_url") or ""),
        )
    )
    for source in recorded:
        source_type = str(source.get("source_type") or "")
        label = labels.get(source_type, source_type.replace("_", " ").title())
        url = str(source.get("source_url") or "")
        title = str(source.get("title") or url)
        rows.append(
            "<tr>"
            f"<td>{_SITE_DISCOVERY._esc(label)}</td>"
            f'<td class="url"><a href="{_SITE_DISCOVERY._esc(url)}" target="_blank" '
            f'rel="nofollow noopener noreferrer">{_SITE_DISCOVERY._esc(title)}</a><br>'
            f'<span class="muted">{_SITE_DISCOVERY._esc(url)}</span></td>'
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="2"><span class="muted">No public source URL is currently recorded.</span></td></tr>')
    return (
        "<table><thead><tr><th>Source type</th><th>Reference</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_vendor_page(
    config: Any,
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    commit_sha: str,
    snapshot_date: str,
) -> str:
    """Remove source-health and maintenance fields from the human vendor page."""
    page = _ORIGINAL_RENDER_VENDOR_PAGE(
        config,
        vendor,
        sources,
        commit_sha=commit_sha,
        snapshot_date=snapshot_date,
    )
    replacement = (
        "      <h2>Public assurance sources</h2>\n"
        f"      {_public_source_table(sources)}\n\n"
        "      <h2>Machine-readable export</h2>"
    )
    page, replacements = re.subn(
        r"      <h2>Public assurance sources</h2>\n.*?\n      <h2>Machine-readable export</h2>",
        replacement,
        page,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise ValueError("could not replace the public vendor source table")
    return page


_CORE.release_tag = release_tag
_CORE.build_meta = build_meta
_CORE.build_compiled_catalog = build_compiled_catalog
_CORE.render_index_html = render_index_html
_SITE_DISCOVERY.render_vendor_page = render_vendor_page
_CORE.build_discovery.__globals__["render_vendor_page"] = render_vendor_page


def main() -> int:
    return _CORE.main()


if __name__ == "__main__":
    raise SystemExit(main())
