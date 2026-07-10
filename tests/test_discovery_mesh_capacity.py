from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.discovery_mesh_runner import selected_vendor_paths


def write_vendor(root: Path, vendor_id: str) -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": vendor_id,
                "official_domains": [f"{vendor_id}.example"],
                "public_entrypoints": [f"https://{vendor_id}.example"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_default_selection_has_no_vendor_catalog_cap(tmp_path: Path) -> None:
    for index in range(750):
        write_vendor(tmp_path, f"vendor-{index:04d}")

    selected = selected_vendor_paths(root=tmp_path, shard_index=0, shard_count=1)

    assert len(selected) == 750


def test_shards_partition_full_catalog_without_dropping_vendors(tmp_path: Path) -> None:
    for index in range(1_250):
        write_vendor(tmp_path, f"vendor-{index:04d}")

    selected = []
    for shard_index in range(16):
        selected.extend(
            path.parent.name
            for path in selected_vendor_paths(
                root=tmp_path,
                shard_index=shard_index,
                shard_count=16,
            )
        )

    assert len(selected) == 1_250
    assert len(set(selected)) == 1_250
