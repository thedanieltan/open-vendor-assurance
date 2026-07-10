from pathlib import Path

import yaml


ISSUE_TEMPLATE_DIR = Path(".github/ISSUE_TEMPLATE")
WORKFLOW_DIR = Path(".github/workflows")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    # PyYAML uses YAML 1.1 boolean parsing, where the plain scalar key `on`
    # is parsed as True. GitHub Actions treats it as the trigger key.
    return workflow.get("on") or workflow.get(True) or {}


def test_public_issue_template_list_is_consolidated_for_non_devs():
    templates = sorted(path.name for path in ISSUE_TEMPLATE_DIR.glob("*.yml"))

    # WP30 deliberately adds a separate source-claim intake lane. These forms
    # are contributor-facing but do not enter the catalog-agent lane.
    assert templates == [
        "boundary-question.yml",
        "bug-report.yml",
        "catalog-update.yml",
        "config.yml",
        "docs-improvement.yml",
        "submission-broken-source.yml",
        "submission-machine-readable.yml",
        "submission-new-source.yml",
        "submission-new-vendor.yml",
        "submission-subprocessor-feed.yml",
        "submission-vendor-identity.yml",
    ]


def test_catalog_update_template_covers_add_update_and_guardrails():
    template = load_yaml(ISSUE_TEMPLATE_DIR / "catalog-update.yml")
    text = (ISSUE_TEMPLATE_DIR / "catalog-update.yml").read_text(encoding="utf-8")
    fields = {
        item["id"]: item
        for item in template["body"]
        if isinstance(item, dict) and "id" in item
    }

    assert template["name"] == "Vendor catalog update"
    assert template["title"] == "Catalog update: "
    assert "area:catalog" in template["labels"]
    assert "lane:catalog-agent" in template["labels"]
    assert fields["request_type"]["attributes"]["options"] == [
        "Add a new vendor",
        "Add a public source to an existing vendor",
        "Correct an existing source URL",
        "Mark a source as moved or retired",
        "Correct vendor metadata",
        "Correct source title, language, date, or type",
        "Other factual catalog update",
    ]
    assert "source_type" not in fields
    assert "source_language" not in fields
    assert "contributor_context" in fields
    assert "agent will classify metadata" in text
    assert "anti-bot bypass" in text
    assert "login-only documents" in text
    assert "This update is factual public metadata only." in text


def test_scope_template_absorbs_out_of_scope_question_path():
    template = load_yaml(ISSUE_TEMPLATE_DIR / "boundary-question.yml")
    text = (ISSUE_TEMPLATE_DIR / "boundary-question.yml").read_text(encoding="utf-8")

    assert template["name"] == "Scope or boundary question"
    assert "Legal or compliance interpretation request" in text
    assert "Vendor risk scoring request" in text
    assert "Bot-protection or access-control bypass request" in text
    assert "OpenVA does not bypass anti-bot systems" in text


def test_contribution_intake_agent_opens_machine_gated_prs_without_default_human_review():
    workflow = load_yaml(WORKFLOW_DIR / "contribution-intake-agent.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "contribution-intake-agent.yml").read_text(encoding="utf-8")

    assert workflow["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "issues": "write",
    }
    assert set(triggers.keys()) == {"issues", "workflow_dispatch"}
    assert triggers["issues"]["types"] == ["opened", "edited", "labeled"]
    assert "python -m tools.openva.contribution_intake issue" in text
    assert "--network-check" in text
    assert "python -m tools.openva.catalog_batch" in text
    assert "peter-evans/create-pull-request" in text
    assert "add-paths:" in text
    assert ".openva-intake/*" not in text
    assert "Catalog:" in text
    assert "needs-human-review" not in text
    assert "labels: catalog, agent-generated" in text
    assert "merge" not in text.lower()
