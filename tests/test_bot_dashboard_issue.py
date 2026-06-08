from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_dashboard_issue import main, sync_dashboard_issue

BOT_DASHBOARD_ISSUE_DOC = Path("docs/operations/BOT_DASHBOARD_ISSUE_SYNC.md")
BOT_DASHBOARD_ISSUE = Path("docs/operations/contracts/bot-dashboard-issue.yaml")
OPTIONAL_WORKFLOW = Path(".github/workflows/bot-dashboard-issue.yml")


class FakeIssueClient:
    def __init__(self, issues: list[dict] | None = None) -> None:
        self.issues = issues or []
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def list_open_issues(self, labels: list[str]) -> list[dict]:
        return list(self.issues)

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        issue = {"number": 999, "title": title, "body": body, "labels": labels}
        self.created.append(issue)
        return issue

    def update_issue(self, issue_number: int, body: str) -> dict:
        update = {"number": issue_number, "body": body}
        self.updated.append(update)
        return update


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def make_dashboard(tmp_path: Path, text: str = "# OpenVA Bot Dashboard\n\nBody\n") -> Path:
    path = tmp_path / "bot-dashboard.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_contract_exists_parses_and_points_to_source_document():
    assert BOT_DASHBOARD_ISSUE_DOC.exists()
    contract = load_yaml(BOT_DASHBOARD_ISSUE)

    assert contract["contract"] == "bot-dashboard-issue"
    assert contract["source_document"] == "docs/operations/BOT_DASHBOARD_ISSUE_SYNC.md"
    assert contract["dashboard_source"] == "maintenance/bot-dashboard.md"
    assert contract["issue"]["title"] == "OpenVA Bot Dashboard"


def test_dry_run_default_is_true_and_report_only_default_is_true():
    defaults = load_yaml(BOT_DASHBOARD_ISSUE)["defaults"]

    assert defaults["dry_run"] is True
    assert defaults["report_only"] is True


def test_duplicate_open_issue_policy_is_fail_safe():
    issue = load_yaml(BOT_DASHBOARD_ISSUE)["issue"]

    assert issue["duplicate_policy"] == "fail_if_multiple_open_matching_issues"
    assert issue["create_if_missing"] is True
    assert issue["update_if_present"] is True


def test_generated_report_is_deterministic(tmp_path):
    dashboard = make_dashboard(tmp_path)
    first = sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard)
    second = sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard)

    assert first == second
    assert first["decision"] == "would_create"
    assert first["dry_run"] is True
    assert first["report_only"] is True
    assert first["body_hash"].startswith("sha256:")


def test_missing_dashboard_file_fails_clearly(tmp_path):
    missing = tmp_path / "missing.md"
    report = sync_dashboard_issue(repo="example/repo", dashboard_path=missing)

    assert report["decision"] == "failed"
    assert "dashboard_missing" in report["reasons"]
    assert report["body_hash"] is None
    assert "Generate maintenance/bot-dashboard.md" in report["next_safe_action"]


def test_explicit_issue_number_is_accepted_in_dry_run(tmp_path):
    dashboard = make_dashboard(tmp_path)
    report = sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard, issue_number=123)

    assert report["decision"] == "would_update"
    assert report["target_issue_number"] == 123
    assert report["duplicate_issue_status"] == "not_checked_explicit_issue_number"


def test_multiple_matching_issues_cause_denied_decision(tmp_path):
    dashboard = make_dashboard(tmp_path)
    client = FakeIssueClient(
        [
            {"number": 1, "title": "OpenVA Bot Dashboard"},
            {"number": 2, "title": "OpenVA Bot Dashboard"},
        ]
    )

    report = sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard, client=client)

    assert report["decision"] == "denied"
    assert report["duplicate_issue_status"] == "multiple_open_matching_issues"
    assert report["matching_issue_numbers"] == [1, 2]
    assert "multiple_matching_issues" in report["reasons"]
    assert client.created == []
    assert client.updated == []


def test_single_matching_issue_would_update_in_dry_run(tmp_path):
    dashboard = make_dashboard(tmp_path)
    client = FakeIssueClient([{"number": 7, "title": "OpenVA Bot Dashboard"}])

    report = sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard, client=client)

    assert report["decision"] == "would_update"
    assert report["target_issue_number"] == 7
    assert report["matching_issue_numbers"] == [7]
    assert client.updated == []


def test_report_only_blocks_non_dry_run_issue_mutation(tmp_path):
    dashboard = make_dashboard(tmp_path)
    client = FakeIssueClient([{"number": 7, "title": "OpenVA Bot Dashboard"}])

    report = sync_dashboard_issue(
        repo="example/repo",
        dashboard_path=dashboard,
        client=client,
        dry_run=False,
        report_only=True,
    )

    assert report["decision"] == "denied"
    assert "report_only_blocks_issue_write" in report["reasons"]
    assert client.updated == []


def test_non_dry_run_update_requires_explicit_report_only_disable(tmp_path):
    dashboard = make_dashboard(tmp_path)
    client = FakeIssueClient([{"number": 7, "title": "OpenVA Bot Dashboard"}])

    report = sync_dashboard_issue(
        repo="example/repo",
        dashboard_path=dashboard,
        client=client,
        dry_run=False,
        report_only=False,
    )

    assert report["decision"] == "updated"
    assert client.updated == [{"number": 7, "body": dashboard.read_text(encoding="utf-8")}]


def test_cli_writes_sync_report(tmp_path):
    dashboard = make_dashboard(tmp_path)
    out = tmp_path / "sync-report.json"

    result = main(["sync", "--dashboard", str(dashboard), "--repo", "example/repo", "--dry-run", "--out", str(out)])

    assert result == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["decision"] == "would_create"
    assert report["dry_run"] is True


def test_sync_does_not_mutate_catalog_data(tmp_path):
    before = data_vendor_digest()
    dashboard = make_dashboard(tmp_path)

    sync_dashboard_issue(repo="example/repo", dashboard_path=dashboard)

    assert data_vendor_digest() == before


def test_tool_does_not_mutate_prs_or_dispatch_workflows():
    source = Path("tools/openva/bot_dashboard_issue.py").read_text(encoding="utf-8").lower()

    assert "/pulls" not in source
    assert "/pull/" not in source
    assert "workflow_dispatch" not in source
    assert "actions/workflows" not in source


def test_optional_workflow_permissions_do_not_exceed_issue_sync_needs():
    if not OPTIONAL_WORKFLOW.exists():
        return
    workflow = load_yaml(OPTIONAL_WORKFLOW)

    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert "pull-requests" not in workflow["permissions"]


def test_optional_workflow_defaults_to_dry_run():
    if not OPTIONAL_WORKFLOW.exists():
        return
    workflow = OPTIONAL_WORKFLOW.read_text(encoding="utf-8")

    assert "dry_run" in workflow
    assert "default: true" in workflow
