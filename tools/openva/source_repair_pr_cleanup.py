from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "source_repair_stale_pr_cleanup"
BOT_LOGINS = {"github-actions[bot]", "dependabot[bot]", "renovate[bot]"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def author_login(value: Any) -> str | None:
    if isinstance(value, dict):
        login = value.get("login")
        return str(login) if login else None
    if value:
        return str(value)
    return None


def human_activity(pr: dict[str, Any]) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []
    for field in ("comments", "reviews", "latestReviews"):
        values = pr.get(field) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            login = author_login(item.get("author") or item.get("user"))
            if login and login not in BOT_LOGINS:
                activity.append(
                    {
                        "type": field,
                        "author": login,
                        "created_at": item.get("createdAt") or item.get("submittedAt"),
                    }
                )
    return activity


def compact_pr(pr: dict[str, Any], reason: str, now: datetime) -> dict[str, Any]:
    created = parse_time(str(pr.get("createdAt") or ""))
    age_days = None
    if created is not None:
        age_days = (now - created).days
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "url": pr.get("url"),
        "head_branch": pr.get("headRefName"),
        "author": author_login(pr.get("author")),
        "created_at": pr.get("createdAt"),
        "updated_at": pr.get("updatedAt"),
        "age_days": age_days,
        "reason": reason,
    }


def stale_decision(pr: dict[str, Any], *, now: datetime, stale_days: int) -> tuple[bool, str]:
    title = str(pr.get("title") or "")
    head_branch = str(pr.get("headRefName") or "")
    author = author_login(pr.get("author"))
    created = parse_time(str(pr.get("createdAt") or ""))

    if not title.startswith("Catalog: repair"):
        return False, "non_repair_title"
    if not head_branch.startswith("agent-source-repair"):
        return False, "non_generated_source_repair_branch"
    if author and author != "github-actions[bot]":
        return False, "human_authored_pr"
    if created is None:
        return False, "missing_or_invalid_created_at"
    if now - created < timedelta(days=stale_days):
        return False, "fresh_repair_pr"
    if human_activity(pr):
        return False, "human_activity_detected"
    return True, "stale_generated_repair_pr"


def build_cleanup_report(
    prs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    stale_days: int = 30,
    generated_at: str | None = None,
) -> dict[str, Any]:
    effective_now = now or datetime.now(UTC)
    closed_prs: list[dict[str, Any]] = []
    skipped_prs: list[dict[str, Any]] = []

    for pr in sorted(prs, key=lambda item: int(item.get("number") or 0)):
        should_close, reason = stale_decision(pr, now=effective_now, stale_days=stale_days)
        compact = compact_pr(pr, reason, effective_now)
        if should_close:
            closed_prs.append(compact)
        else:
            skipped_prs.append(compact)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "stale_days": stale_days,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "summary": {
            "scanned_pr_count": len(prs),
            "closed_pr_count": len(closed_prs),
            "skipped_pr_count": len(skipped_prs),
        },
        "closed_prs": closed_prs,
        "skipped_prs": skipped_prs,
    }


def markdown_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Stale Source Repair PR Cleanup",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This report targets stale generated source repair PRs only.",
        "",
        "## Summary",
        "",
        f"- Scanned PRs: `{summary['scanned_pr_count']}`",
        f"- Closed PRs: `{summary['closed_pr_count']}`",
        f"- Skipped PRs: `{summary['skipped_pr_count']}`",
        f"- Stale threshold days: `{report['stale_days']}`",
        "",
        "## Closed PRs",
        "",
    ]
    if not report["closed_prs"]:
        lines.append("No stale generated source repair PRs were selected for closure.")
    else:
        lines.extend(["| PR | Branch | Age days | Reason |", "|---:|---|---:|---|"])
        for pr in report["closed_prs"]:
            lines.append(markdown_row([pr.get("number"), pr.get("head_branch"), pr.get("age_days"), pr.get("reason")]))
    lines.extend(["", "## Skipped PRs", ""])
    if not report["skipped_prs"]:
        lines.append("No PRs were skipped.")
    else:
        lines.extend(["| PR | Title | Branch | Reason |", "|---:|---|---|---|"])
        for pr in report["skipped_prs"]:
            lines.append(markdown_row([pr.get("number"), pr.get("title"), pr.get("head_branch"), pr.get("reason")]))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Only targets PRs titled `Catalog: repair*`.",
            "- Only targets branches beginning `agent-source-repair`.",
            "- Skips human-authored PRs.",
            "- Skips PRs with detected human comments or reviews.",
            "- Does not mutate catalog files.",
            "- Does not generate repair plans or source replacements.",
            "- Does not enable automerge.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-pr-cleanup")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--prs-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("source-repair-stale-pr-cleanup.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("source-repair-stale-pr-cleanup.md"))
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--now")
    args = parser.parse_args(argv)

    prs = load_json(args.prs_json)
    if not isinstance(prs, list):
        raise ValueError(f"{args.prs_json}: expected JSON array")
    if not all(isinstance(pr, dict) for pr in prs):
        raise ValueError(f"{args.prs_json}: expected each PR row to be an object")
    parsed_now = parse_time(args.now) if args.now else None
    if args.now and parsed_now is None:
        raise ValueError("--now must be an ISO-8601 timestamp")
    report = build_cleanup_report(prs, now=parsed_now, stale_days=args.stale_days)
    write_json(report, args.output)
    write_markdown(report, args.markdown_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
