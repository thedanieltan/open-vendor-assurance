from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_discovery_mesh_docs_do_not_define_vendor_cap() -> None:
    capacity = (ROOT / "docs" / "architecture" / "DISCOVERY_MESH_CAPACITY.md").read_text(encoding="utf-8")
    runner = (ROOT / "docs" / "operations" / "discovery-mesh-runner.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs" / "architecture" / "decisions" / "ADR-0010-unbounded-discovery-mesh-catalog.md").read_text(encoding="utf-8")

    assert "does not impose a maximum vendor-catalog size" in capacity
    assert "no default vendor-count cap" in runner
    assert "does not impose a maximum vendor-count ceiling" in adr
