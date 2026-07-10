from pathlib import Path

import pytest

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_rejects_path_traversal_run_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_token"):
        build_vendor_promotion_plans(
            {"actions": []},
            source_plan_path="raw.json",
            run_token="../escape",
            output_root=tmp_path,
        )
