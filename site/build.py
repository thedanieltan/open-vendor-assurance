"""Continuous-publication wrapper for the compiled site builder.

The implementation is preserved byte-for-byte in ``site/build_core.py``. This
wrapper removes the retired formal-release metadata, makes the exact source
commit the sole catalog snapshot identity, and adds the bounded public identity
keys required by the browser resolver.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _validate_catalog_card_interactions() -> None:
    """Fail the site build if selection and detail controls become coupled again."""
    source_path = Path(__file__).with_name("src") / "catalog-card-interactions.js"
    source = source_path.read_text(encoding="utf-8")
    required_tokens = (
        'CATALOG_CARD_INTERACTIONS_VERSION = "explicit-view-links-v2"',
        'selectionButton.className = "vendor-card__select-hit"',
        'detailButton.textContent = "View links"',
        'detailButton.setAttribute("aria-label", `View public links for ${vendorName}`)',
        'checkbox.dispatchEvent(new Event("change", { bubbles: true }))',
    )
    missing = [token for token in required_tokens if token not in source]
    if missing:
        raise ValueError(
            "catalog card interaction contract is incomplete: "
            + ", ".join(repr(token) for token in missing)
        )


def _validate_catalog_donor_alignment() -> None:
    """Keep the added controls visually aligned with the Trusty Vendor Scan donor."""
    source_path = Path(__file__).with_name("src") / "catalog-donor-alignment.js"
    source = source_path.read_text(encoding="utf-8")
    required_tokens = (
        'CATALOG_DONOR_ALIGNMENT_VERSION = "trusty-vendor-scan-v1"',
        'footer.className = "vendor-card__footer"',
        'detailButton.textContent = "View links →"',
        "box-shadow: 0 0 0 1px color-mix(in oklch, var(--donor-brand) 40%, transparent) !important;",
        "background: rgba(15, 27, 61, .22) !important;",
        "box-shadow: var(--donor-shadow) !important;",
    )
    missing = [token for token in required_tokens if token not in source]
    if missing:
        raise ValueError(
            "catalog donor-alignment contract is incomplete: "
            + ", ".join(repr(token) for token in missing)
        )


def _validate_resolver_source_availability() -> None:
    """Keep resolver choices tied to source types present in the current snapshot."""
    source_path = Path(__file__).with_name("src") / "resolver-source-availability.js"
    source = source_path.read_text(encoding="utf-8")
    required_tokens = (
        'RESOLVER_SOURCE_AVAILABILITY_VERSION = "catalog-snapshot-v1"',
        'fetch("data/source-types.json", { cache: "no-store" })',
        ".filter((sourceType) => Number(counts[sourceType] || 0) > 0)",
        "browserResultPackRow = availabilityAwareResultPackRow;",
        "a blank download cell means no indexed URL for that vendor and source type",
        "Defined by the schema but not currently indexed:",
    )
    missing = [token for token in required_tokens if token not in source]
    if missing:
        raise ValueError(
            "resolver source-availability contract is incomplete: "
            + ", ".join(repr(token) for token in missing)
        )


def render_index_html(template: str, config: Any) -> str:
    """Load focused public interaction layers after the existing site runtime."""
    _validate_catalog_card_interactions()
    _validate_catalog_donor_alignment()
    _validate_resolver_source_availability()
    page = _ORIGINAL_RENDER_INDEX_HTML(template, config)
    marker = '    <script src="ui-fixes.js?v=20260713-phase2"></script>'
    replacement = (
        '    <script src="public-vendor-detail.js?v=20260713-vendor-detail"></script>\n'
        '    <script src="catalog-navigation.js?v=20260714-pagination-drawer"></script>\n'
        '    <script src="catalog-card-interactions.js?v=20260715-explicit-view-links"></script>\n'
        '    <script src="catalog-donor-alignment.js?v=20260715-trusty-vendor-scan"></script>\n'
        + marker
        + '\n    <script src="resolver-source-availability.js?v=20260715-catalog-snapshot"></script>'
    )
    if marker not in page:
        raise ValueError("could not locate the public interaction script insertion point")
    return page.replace(marker, replacement, 1)


_CORE.release_tag = release_tag
_CORE.build_meta = build_meta
_CORE.build_compiled_catalog = build_compiled_catalog
_CORE.render_index_html = render_index_html


def main() -> int:
    return _CORE.main()


if __name__ == "__main__":
    raise SystemExit(main())
