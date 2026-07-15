from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "discovery-mesh.yml"


def test_scheduled_mesh_uses_selective_rendered_discovery_without_browser_download() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'pip install "playwright==1.57.0"' in text
    assert 'CHROMIUM="$(command -v chromium)"' in text
    assert 'echo "OPENVA_CHROMIUM_EXECUTABLE=$CHROMIUM" >> "$GITHUB_ENV"' in text
    assert "playwright install" not in text
    assert "python -m tools.openva.rendered_discovery_runner" in text
    assert "tools.openva.discovery_mesh_runner shard" not in text


def test_scheduled_mesh_resolves_finite_render_bounds_without_catalog_cap() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "RENDER_MAX_PAGES_PER_VENDOR" in text
    assert "RENDER_MAX_REQUESTS_PER_PAGE" in text
    assert "RENDER_MAX_BYTES_PER_PAGE" in text
    assert "RENDER_TIMEOUT_MS" in text
    assert "RENDER_SETTLE_MS" in text
    assert '--max-render-pages-per-vendor "$MESH_RENDER_MAX_PAGES"' in text
    assert '--max-render-requests-per-page "$MESH_RENDER_MAX_REQUESTS"' in text
    assert '--max-render-bytes-per-page "$MESH_RENDER_MAX_BYTES"' in text
    assert "scheduled discovery mesh must not define a catalog vendor cap" in text


def test_relevant_main_push_runs_bounded_read_only_deployment_smoke() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in text
    assert 'branches: [main]' in text
    assert 'REQUESTED_SHARD_COUNT: "${{ github.event_name == \'push\' && \'1\'' in text
    assert 'REQUESTED_VENDOR_LIMIT: "${{ github.event_name == \'push\' && \'25\'' in text
    assert "if: github.event_name != 'push'" in text
    assert "scheduled discovery mesh must not define a catalog vendor cap" in text


def test_aggregate_publishes_rendered_discovery_differential() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Build rendered-discovery differential report" in text
    assert '"report_type": "rendered_discovery_differential"' in text
    assert '"baseline": "bounded_static_html_discovery"' in text
    assert '"browser_direct_network_access": False' in text
    assert '"rendered_signals_are_catalog_facts": False' in text
    assert "vendors_with_javascript_fallback_eligibility" in text
    assert "vendors_with_rendered_verified_candidates" in text
    assert "reports/discovery-mesh/rendered-discovery-differential.json" in text
