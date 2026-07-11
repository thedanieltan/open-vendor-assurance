"""Continuous-publication wrapper for the compiled site builder.

The implementation is preserved byte-for-byte in ``site/build_core.py``. This
wrapper removes the retired formal-release metadata and makes the exact source
commit the sole catalog snapshot identity.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_CORE_PATH = Path(__file__).with_name("build_core.py")
_SPEC = importlib.util.spec_from_file_location("openva_site_build_core", _CORE_PATH)
assert _SPEC and _SPEC.loader
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)

for _name, _value in vars(_CORE).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

_ORIGINAL_BUILD_META = _CORE.build_meta


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


_CORE.release_tag = release_tag
_CORE.build_meta = build_meta


def main() -> int:
    return _CORE.main()


if __name__ == "__main__":
    raise SystemExit(main())
