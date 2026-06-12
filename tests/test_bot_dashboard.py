from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import yaml

from tools.openva.bot_dashboard import render_dashboard, write_dashboard

BOT_DASHBOARD_DOC = Path("docs/operations/BOT_DASHBOARD.md")
BOT_DASHBOARD_CONTRACT = Path("docs/operations/contracts/bot-dashboard.yaml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_dashboard_contract_exists_parses_and_points_to_source_document():
    assert BOT_DASHBOARD_DOC.exists()
    assert BOT_DASHBOARD_CONTRACT.exists()

    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    assert contract["contract"] == "bot-dashboard"
    assert contract["source_document"] == "docs/operations/BOT_DASHBOARD.md"
    assert contract["output_path"] == "maintenance/bot-dashboard.md"
    assert contract["dashboard_issue"]["create_or_update_enabled"] is False


def test_dashboard_contract_expected_sections_exist_in_docs_and_rendered_markdown():
    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    doc = BOT_DASHBOARD_DOC.read_text(encoding="utf-8")
    rendered = render_dashboard()

    for section in contract["expected_sections"]:
        assert section["id"]
        assert section["title"] in doc
        assert f"## {section['title']}" in rendered


def test_dashboard_lane_and_failure_summaries_match_wp9_contracts():
    dashboard = load_yaml(BOT_DASHBOARD_CONTRACT)
    authority_lane_ids = {lane["id"] for lane in load_yaml(BOT_AUTHORITY)["lanes"]}
    failure_codes = {entry["code"] for entry in load_yaml(BOT_FAILURE_TAXONOMY)["failure_classes"]}

    assert "bot_chatops_hold" in dashboard["summarized_authority_lanes"]
    assert set(dashboard["summarized_authority_lanes"]) == authority_lane_ids
    assert set(dashboard["summarized_failure_classes"]) == failure_codes


def test_renderer_succeeds_with_missing_optional_artifacts(tmp_path):
    docs_contracts = tmp_path / "docs/operations/contracts"
    docs_contracts.mkdir(parents=True)
    for path in (BOT_AUTHORITY, BOT_FAILURE_TAXONOMY, BOT_QUEUE_POLICY, BOT_DASHBOARD_CONTRACT):
        shutil.copy2(path, docs_contracts / path.name)

    markdown = render_dashboard(tmp_path)

    assert "## Missing Local Artifacts" in markdown
    assert "not_available_in_local_checkout" in markdown
    assert "## Next Safe Action" in markdown


def test_generated_markdown_is_deterministic(tmp_path):
    docs_contracts = tmp_path / "docs/operations/contracts"
    docs_contracts.mkdir(parents=True)
    for path in (BOT_AUTHORITY, BOT_FAILURE_TAXONOMY, BOT_QUEUE_POLICY, BOT_DASHBOARD_CONTRACT):
        shutil.copy2(path, docs_contracts / path.name)

    first = render_dashboard(tmp_path)
    second = render_dashboard(tmp_path)

    assert first == second


def test_generated_markdown_includes_queue_limits_and_stale_evidence_thresholds():
    markdown = render_dashboard()
    queue = load_yaml(BOT_QUEUE_POLICY)

    assert f"Max open catalog-growth PRs: `{queue['global']['max_open_catalog_growth_prs']}`" in markdown
    assert f"Max bot PRs per day: `{queue['global']['max_bot_prs_per_day']}`" in markdown
    assert f"Cooldown after failure hours: `{queue['global']['cooldown_after_failure_hours']}`" in markdown
    for name, hours in queue["global"]["stale_evidence_max_age_hours"].items():
        assert f"`{name}`: `{hours}` hours" in markdown


def test_generated_markdown_includes_next_safe_action_and_no_deprecated_terms():
    markdown = render_dashboard()
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])

    assert "## Next Safe Action" in markdown
    assert "next safe action" in markdown.lower() or "controlled promotion" in markdown
    for term in deprecated_terms:
        assert term not in markdown


def test_renderer_does_not_modify_catalog_data(tmp_path):
    before = data_vendor_digest()
    output = tmp_path / "bot-dashboard.md"

    written = write_dashboard(output_path=output)

    assert written == output
    assert output.exists()
    assert data_vendor_digest() == before
