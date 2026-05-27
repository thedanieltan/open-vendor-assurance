from __future__ import annotations

import json
from pathlib import Path

from tools.openva.strict_growth_automerge import main

HEAD = "head-sha"
BASE = "base-sha"


def write_json(path: Path, data: dict) -> Path:
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
