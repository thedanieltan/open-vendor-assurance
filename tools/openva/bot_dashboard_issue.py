from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_DASHBOARD_ISSUE = Path("docs/operations/contracts/bot-dashboard-issue.yaml")
DEFAULT_REPORT = Path("maintenance/bot-dashboard-issue-sync-report.json")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def body_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def detect_token(env: dict[str, str] | None = None) -> str | None:
    env = env or os.environ
    return env.get("OPENVA_GITHUB_TOKEN") or env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")


class GitHubIssueClient:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"https://api.github.com/repos/{self.repo}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_open_issues(self, labels: list[str]) -> list[dict[str, Any]]:
        query = urlencode({"state": "open", "labels": ",".join(labels), "per_page": 100})
        issues = self._request("GET", f"/issues?{query}")
        return [issue for issue in issues if "pull_request" not in issue]

    def get_issue(self, issue_number: int) -> dict[str, Any]:
        return self._request("GET", f"/issues/{issue_number}")

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        return self._request("POST", "/issues", {"title": title, "body": body, "labels": labels})

    def update_issue(self, issue_number: int, body: str) -> dict[str, Any]:
        return self._request("PATCH", f"/issues/{issue_number}", {"body": body})


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return load_yaml(root / BOT_DASHBOARD_ISSUE)


def report(
    *,
    decision: str,
    contract: dict[str, Any],
    repo: str,
    dashboard_path: Path,
    dry_run: bool,
    report_only: bool,
    body: str | None,
    target_issue_number: int | None,
    duplicate_issue_status: str,
    matching_issue_numbers: list[int],
    reasons: list[str],
) -> dict[str, Any]:
    issue = contract["issue"]
    return {
        "version": 1,
        "report_type": "bot_dashboard_issue_sync",
        "decision": decision,
        "repo": repo,
        "dashboard_source": dashboard_path.as_posix(),
        "target_issue_title": issue["title"],
        "target_issue_number": target_issue_number,
        "issue_labels": list(issue["labels"]),
        "duplicate_issue_status": duplicate_issue_status,
        "matching_issue_numbers": matching_issue_numbers,
        "dry_run": dry_run,
        "report_only": report_only,
        "body_hash": body_hash(body) if body is not None else None,
        "reasons": reasons,
        "next_safe_action": next_safe_action(decision, reasons),
    }


def next_safe_action(decision: str, reasons: list[str]) -> str:
    if "dashboard_missing" in reasons:
        return "Generate maintenance/bot-dashboard.md before attempting dashboard issue sync."
    if "multiple_matching_issues" in reasons:
        return "Manually consolidate duplicate dashboard issues before enabling sync."
    if "report_only_blocks_issue_write" in reasons:
        return "Keep report-only mode or explicitly enable issue update in a reviewed operator run."
    if "token_missing" in reasons:
        return "Provide a GitHub token only when a reviewed non-dry-run issue update is intended."
    if "explicit_issue_title_mismatch" in reasons:
        return "Do not update the explicit issue number until maintainers confirm it is the persistent dashboard issue."
    if decision == "would_create":
        return "Review the dry-run report, then create one dashboard issue only if maintainers approve."
    if decision == "would_update":
        return "Review the dry-run body hash, then update the persistent dashboard issue only if approved."
    if decision in {"created", "updated"}:
        return "Use the persistent dashboard issue as the single bot control issue."
    return "Do not mutate GitHub issue state until the reported blocker is resolved."


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Bot Dashboard Issue Sync Report",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Dry-run: `{report['dry_run']}`",
        f"- Report-only: `{report['report_only']}`",
        f"- Target issue title: `{report['target_issue_title']}`",
        f"- Target issue number: `{report['target_issue_number']}`",
        f"- Duplicate issue status: `{report['duplicate_issue_status']}`",
        f"- Body hash: `{report['body_hash']}`",
        "",
        "## Reasons",
        "",
    ]
    for reason in report["reasons"]:
        lines.append(f"- `{reason}`")
    lines.extend(["", "## Next Safe Action", "", f"- {report['next_safe_action']}", ""])
    return "\n".join(lines)


def matching_issues_by_title(issues: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    return [issue for issue in issues if issue.get("title") == title]


def sync_dashboard_issue(
    *,
    repo: str,
    dashboard_path: Path,
    issue_number: int | None = None,
    dry_run: bool | None = None,
    report_only: bool | None = None,
    contract: dict[str, Any] | None = None,
    client: Any | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    dashboard = dashboard_path if dashboard_path.is_absolute() else ROOT / dashboard_path
    dry_run = contract["defaults"]["dry_run"] if dry_run is None else dry_run
    report_only = contract["defaults"]["report_only"] if report_only is None else report_only
    issue = contract["issue"]
    labels = list(issue["labels"])

    if not dashboard.exists():
        return report(
            decision="failed",
            contract=contract,
            repo=repo,
            dashboard_path=dashboard_path,
            dry_run=dry_run,
            report_only=report_only,
            body=None,
            target_issue_number=issue_number,
            duplicate_issue_status="not_checked_dashboard_missing",
            matching_issue_numbers=[],
            reasons=["dashboard_missing"],
        )

    body = dashboard.read_text(encoding="utf-8")
    reasons: list[str] = []
    duplicate_status = "not_checked"
    matching_numbers: list[int] = []
    target_number = issue_number

    if client is None and token:
        client = GitHubIssueClient(repo, token)

    if issue_number is not None:
        duplicate_status = "not_checked_explicit_issue_number"
        decision = "would_update"
    elif client is None:
        duplicate_status = "not_checked_no_token"
        decision = "would_create" if issue.get("create_if_missing") else "denied"
        if not dry_run:
            reasons.append("token_missing")
            decision = "denied"
    else:
        matches = matching_issues_by_title(client.list_open_issues(labels), issue["title"])
        matching_numbers = [int(match["number"]) for match in matches]
        if len(matches) > 1:
            duplicate_status = "multiple_open_matching_issues"
            reasons.append("multiple_matching_issues")
            decision = "denied"
        elif len(matches) == 1:
            duplicate_status = "one_open_matching_issue"
            target_number = int(matches[0]["number"])
            decision = "would_update" if issue.get("update_if_present") else "denied"
        else:
            duplicate_status = "no_open_matching_issue"
            decision = "would_create" if issue.get("create_if_missing") else "denied"

    if decision in {"would_create", "would_update"} and report_only and not dry_run:
        reasons.append("report_only_blocks_issue_write")
        decision = "denied"

    if decision in {"would_create", "would_update"} and dry_run:
        reasons.append(f"{decision}_dry_run")
        return report(
            decision=decision,
            contract=contract,
            repo=repo,
            dashboard_path=dashboard_path,
            dry_run=dry_run,
            report_only=report_only,
            body=body,
            target_issue_number=target_number,
            duplicate_issue_status=duplicate_status,
            matching_issue_numbers=matching_numbers,
            reasons=reasons,
        )

    if decision == "would_create":
        if client is None:
            reasons.append("token_missing")
            decision = "denied"
        else:
            created = client.create_issue(issue["title"], body, labels)
            target_number = int(created["number"])
            decision = "created"
            reasons.append("issue_created")
    elif decision == "would_update":
        if client is None:
            reasons.append("token_missing")
            decision = "denied"
        else:
            if target_number is None:
                reasons.append("target_issue_number_missing")
                decision = "failed"
            else:
                if issue_number is not None:
                    target_issue = client.get_issue(target_number)
                    if target_issue.get("title") != issue["title"] or "pull_request" in target_issue:
                        reasons.append("explicit_issue_title_mismatch")
                        decision = "denied"
                    else:
                        client.update_issue(target_number, body)
                        decision = "updated"
                        reasons.append("issue_updated")
                else:
                    client.update_issue(target_number, body)
                    decision = "updated"
                    reasons.append("issue_updated")

    if not reasons:
        reasons.append("decision_recorded")

    return report(
        decision=decision,
        contract=contract,
        repo=repo,
        dashboard_path=dashboard_path,
        dry_run=dry_run,
        report_only=report_only,
        body=body,
        target_issue_number=target_number,
        duplicate_issue_status=duplicate_status,
        matching_issue_numbers=matching_numbers,
        reasons=reasons,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-dashboard-issue")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--dashboard", type=Path, default=None)
    sync_parser.add_argument("--repo", required=True)
    sync_parser.add_argument("--out", type=Path, default=ROOT / DEFAULT_REPORT)
    sync_parser.add_argument("--out-md", type=Path, default=None)
    sync_parser.add_argument("--issue-number", type=int, default=None)
    sync_parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode.")
    sync_parser.add_argument("--apply", action="store_true", help="Allow non-dry-run issue sync when report-only is disabled.")
    sync_parser.add_argument("--report-only", action="store_true", help="Force report-only mode.")
    sync_parser.add_argument("--allow-issue-update", action="store_true", help="Disable report-only issue-write block.")
    args = parser.parse_args(argv)

    if args.command == "sync":
        contract = load_contract()
        dashboard = args.dashboard or Path(str(contract["dashboard_source"]))
        dry_run = True if args.dry_run else (False if args.apply else contract["defaults"]["dry_run"])
        report_only = True if args.report_only else (False if args.allow_issue_update else contract["defaults"]["report_only"])
        token = detect_token()
        result = sync_dashboard_issue(
            repo=args.repo,
            dashboard_path=dashboard,
            issue_number=args.issue_number,
            dry_run=dry_run,
            report_only=report_only,
            contract=contract,
            token=token,
        )
        out = args.out if args.out.is_absolute() else ROOT / args.out
        write_json(out, result)
        if args.out_md is not None:
            out_md = args.out_md if args.out_md.is_absolute() else ROOT / args.out_md
            write_text(out_md, render_markdown(result))
        print(json.dumps({"decision": result["decision"], "reasons": result["reasons"]}, sort_keys=True))
        return 1 if result["decision"] in {"denied", "failed"} else 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
