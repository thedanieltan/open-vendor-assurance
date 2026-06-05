from __future__ import annotations

import json
from pathlib import Path

from tools.openva.strict_growth_automerge import main

HEAD = "head-sha"
BASE = "base-sha"


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def promotion_plan() -> dict:
    return {
        "report_type": "candidate_promotion_plan",
        "generated_at": "2026-05-27T07:00:00Z",
        "head_sha": HEAD,
        "base_sha": BASE,
        "actions": [
            {
                "action": "strict_catalog_growth_promotion",
                "vendor": {
                    "candidate_vendor_id": "candidate-a",
                    "display_name_candidate": "Candidate A",
                    "official_domain_candidate": "candidate-a.example",
                },
                "source": {
                    "candidate_source_id": "candidate-a-security-page-candidate",
                    "source_type_candidate": "security_page",
                    "candidate_url": "https://candidate-a.example/security",
                },
                "requires_human_review": False,
                "strict_machine_candidate": True,
                "non_advisory": True,
            }
        ],
    }


def eligibility_report() -> dict:
    return {
        "report_type": "catalog_growth_eligibility_report",
        "generated_at": "2026-05-27T07:00:00Z",
        "head_sha": HEAD,
        "base_sha": BASE,
    }


def test_cli_loads_plan_and_eligibility_report_files(tmp_path):
    plan_path = write_json(tmp_path / "promotion-plan.json", promotion_plan())
    eligibility_path = write_json(tmp_path / "eligibility-report.json", eligibility_report())

    assert main(
        [
            "--promotion-plan",
            str(plan_path),
            "--eligibility-report",
            str(eligibility_path),
            "--labels",
            "catalog-growth,automerge:strict-growth",
            "--current-head-sha",
            HEAD,
            "--recorded-head-sha",
            HEAD,
            "--current-base-sha",
            BASE,
            "--recorded-base-sha",
            BASE,
            "--now",
            "2026-05-27T08:00:00Z",
        ]
    ) == 0


def test_cli_returns_nonzero_for_missing_strict_machine_candidate(tmp_path):
    plan = promotion_plan()
    del plan["actions"][0]["strict_machine_candidate"]
    plan_path = write_json(tmp_path / "promotion-plan.json", plan)

    assert main(
        [
            "--promotion-plan",
            str(plan_path),
            "--labels",
            "catalog-growth,automerge:strict-growth",
            "--current-head-sha",
            HEAD,
            "--recorded-head-sha",
            HEAD,
            "--current-base-sha",
            BASE,
            "--recorded-base-sha",
            BASE,
            "--now",
            "2026-05-27T08:00:00Z",
        ]
    ) == 1


def pr_body(plan_path: str, sha256: str, action_count: int = 1) -> str:
    return f"""
## Input

- Promotion plan: `{plan_path}`
- Promotion plan SHA-256: `{sha256}`
- Action count: `{action_count}`
- Strict-growth eligibility report: `maintenance/generated/strict-growth-eligibility-report.json`
- Base SHA: `0123456789abcdef0123456789abcdef01234567`
- Head SHA: `abcdef0123456789abcdef0123456789abcdef01`
""".lstrip()


def test_extract_inputs_writes_strict_growth_env_file(tmp_path):
    plan_path = write_json(
        tmp_path / "maintenance/generated/strict-growth-promotion-plan.json",
        promotion_plan(),
    )
    write_json(
        tmp_path / "maintenance/generated/strict-growth-eligibility-report.json",
        eligibility_report(),
    )
    digest = "sha256:" + __import__("hashlib").sha256(plan_path.read_bytes()).hexdigest()
    body_path = tmp_path / "pr-body.md"
    output_path = tmp_path / "strict-growth-inputs.env"
    body_path.write_text(
        pr_body("maintenance/generated/strict-growth-promotion-plan.json", digest),
        encoding="utf-8",
    )

    assert main(
        [
            "extract-inputs",
            "--body-file",
            str(body_path),
            "--output",
            str(output_path),
            "--repo-root",
            str(tmp_path),
        ]
    ) == 0

    env = output_path.read_text(encoding="utf-8")
    assert "PROMOTION_PLAN_PATH=maintenance/generated/strict-growth-promotion-plan.json" in env
    assert f"PROMOTION_PLAN_SHA256={digest}" in env
    assert "PROMOTION_PLAN_ACTION_COUNT=1" in env
    assert "ELIGIBILITY_REPORT_PATH=maintenance/generated/strict-growth-eligibility-report.json" in env
    assert "STRICT_GROWTH_HEAD_SHA=abcdef0123456789abcdef0123456789abcdef01" in env


def test_extract_inputs_rejects_missing_promotion_plan(tmp_path):
    body_path = tmp_path / "pr-body.md"
    output_path = tmp_path / "strict-growth-inputs.env"
    body_path.write_text(
        """
## Input

- Promotion plan SHA-256: `sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef`
- Action count: `1`
- Strict-growth eligibility report: `maintenance/generated/strict-growth-eligibility-report.json`
- Head SHA: `abcdef0123456789abcdef0123456789abcdef01`
""".lstrip(),
        encoding="utf-8",
    )

    assert main(
        [
            "extract-inputs",
            "--body-file",
            str(body_path),
            "--output",
            str(output_path),
            "--repo-root",
            str(tmp_path),
        ]
    ) == 1
    assert not output_path.exists()


def test_extract_inputs_rejects_non_strict_growth_plan_path(tmp_path):
    plan_path = write_json(tmp_path / "maintenance/reviewed/promotion-plan.json", promotion_plan())
    write_json(
        tmp_path / "maintenance/generated/strict-growth-eligibility-report.json",
        eligibility_report(),
    )
    digest = "sha256:" + __import__("hashlib").sha256(plan_path.read_bytes()).hexdigest()
    body_path = tmp_path / "pr-body.md"
    body_path.write_text(pr_body("maintenance/reviewed/promotion-plan.json", digest), encoding="utf-8")

    assert main(
        [
            "extract-inputs",
            "--body-file",
            str(body_path),
            "--output",
            str(tmp_path / "strict-growth-inputs.env"),
            "--repo-root",
            str(tmp_path),
        ]
    ) == 1


def test_extract_inputs_rejects_missing_plan_file(tmp_path):
    write_json(
        tmp_path / "maintenance/generated/strict-growth-eligibility-report.json",
        eligibility_report(),
    )
    body_path = tmp_path / "pr-body.md"
    body_path.write_text(
        pr_body(
            "maintenance/generated/strict-growth-promotion-plan.json",
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "extract-inputs",
            "--body-file",
            str(body_path),
            "--output",
            str(tmp_path / "strict-growth-inputs.env"),
            "--repo-root",
            str(tmp_path),
        ]
    ) == 1
