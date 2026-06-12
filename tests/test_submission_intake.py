import json
from pathlib import Path

import yaml


ISSUE_TEMPLATE_DIR = Path(".github/ISSUE_TEMPLATE")
SOURCE_SCHEMA = Path("schemas/openva/source-reference.schema.json")
SUBMISSION_GUIDE = Path("docs/submission-intake.md")

SUBMISSION_TEMPLATES = {
    "submission-new-vendor.yml": {
        "name": "New vendor candidate",
        "title": "Vendor candidate: ",
        "labels": ["status:needs-triage", "submission:new-vendor"],
    },
    "submission-new-source.yml": {
        "name": "New assurance source",
        "title": "Source candidate: ",
        "labels": ["status:needs-triage", "submission:new-source"],
    },
    "submission-broken-source.yml": {
        "name": "Broken or moved source",
        "title": "Broken source: ",
        "labels": ["status:needs-triage", "submission:broken-source"],
    },
    "submission-vendor-identity.yml": {
        "name": "Vendor rename or domain change",
        "title": "Vendor identity: ",
        "labels": ["status:needs-triage", "submission:vendor-identity"],
    },
    "submission-subprocessor-feed.yml": {
        "name": "New subprocessor update feed",
        "title": "Subprocessor feed: ",
        "labels": [
            "status:needs-triage",
            "submission:new-source",
            "submission:machine-readable",
        ],
    },
    "submission-machine-readable.yml": {
        "name": "Machine-readable source surface",
        "title": "Machine-readable surface: ",
        "labels": ["status:needs-triage", "submission:machine-readable"],
    },
}

MACHINE_READABLE_SURFACE_OPTIONS = [
    "none",
    "rss",
    "sitemap",
    "llms_txt",
    "openapi",
    "mcp",
    "api",
]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def template_fields(template: dict) -> dict:
    return {
        item["id"]: item
        for item in template["body"]
        if isinstance(item, dict) and "id" in item
    }


def source_type_enum() -> list[str]:
    schema = json.loads(SOURCE_SCHEMA.read_text(encoding="utf-8"))
    return schema["properties"]["source_type"]["enum"]


def test_all_submission_templates_exist_and_parse():
    for filename in SUBMISSION_TEMPLATES:
        path = ISSUE_TEMPLATE_DIR / filename
        assert path.exists(), filename
        template = load_yaml(path)
        assert isinstance(template["body"], list), filename


def test_submission_templates_carry_expected_routing_labels():
    for filename, expected in SUBMISSION_TEMPLATES.items():
        template = load_yaml(ISSUE_TEMPLATE_DIR / filename)
        assert template["name"] == expected["name"], filename
        assert template["title"] == expected["title"], filename
        assert template["labels"] == expected["labels"], filename


def test_submission_templates_never_enter_catalog_agent_lane():
    # Safety-critical: contribution-intake-agent.yml activates on the
    # area:catalog label or the "Catalog update:" title prefix. Submission
    # forms are human claim intake, not a bot lane, so they must carry
    # neither signal and no lane:* label at all.
    for filename in SUBMISSION_TEMPLATES:
        template = load_yaml(ISSUE_TEMPLATE_DIR / filename)
        labels = template["labels"]
        assert "area:catalog" not in labels, filename
        assert not any(label.startswith("lane:") for label in labels), filename
        assert not template["title"].startswith("Catalog update:"), filename


def test_submission_templates_collect_core_claim_fields():
    expected_fields = {
        "submission-new-vendor.yml": [
            "vendor_name",
            "vendor_domain",
            "known_public_sources",
            "why_this_is_authoritative",
            "public_access_confirmed",
            "machine_readable_surface",
            "submitter_notes",
        ],
        "submission-new-source.yml": [
            "vendor_name",
            "vendor_domain",
            "source_url",
            "source_type",
            "canonical_location_belief",
            "why_this_is_authoritative",
            "public_access_confirmed",
            "machine_readable_surface",
            "submitter_notes",
        ],
        "submission-broken-source.yml": [
            "vendor_name",
            "vendor_domain",
            "source_url",
            "observed_state",
            "replacement_url",
            "public_access_confirmed",
            "submitter_notes",
        ],
        "submission-vendor-identity.yml": [
            "vendor_name",
            "vendor_domain",
            "previous_vendor_name",
            "previous_vendor_domain",
            "announcement_url",
            "why_this_is_authoritative",
            "public_access_confirmed",
            "submitter_notes",
        ],
        "submission-subprocessor-feed.yml": [
            "vendor_name",
            "vendor_domain",
            "source_url",
            "subprocessor_list_url",
            "machine_readable_surface",
            "why_this_is_authoritative",
            "public_access_confirmed",
            "submitter_notes",
        ],
        "submission-machine-readable.yml": [
            "vendor_name",
            "vendor_domain",
            "source_url",
            "machine_readable_surface",
            "why_this_is_authoritative",
            "public_access_confirmed",
            "submitter_notes",
        ],
    }

    for filename, field_ids in expected_fields.items():
        fields = template_fields(load_yaml(ISSUE_TEMPLATE_DIR / filename))
        for field_id in field_ids:
            assert field_id in fields, f"{filename}: {field_id}"

    # These forms intentionally have no single source URL field: new-vendor
    # collects optional known source URLs, vendor-identity collects an
    # announcement URL.
    for filename in ("submission-new-vendor.yml", "submission-vendor-identity.yml"):
        fields = template_fields(load_yaml(ISSUE_TEMPLATE_DIR / filename))
        assert "source_url" not in fields, filename


def test_source_type_dropdowns_match_schema_enum():
    enum = source_type_enum()
    for filename in (
        "submission-new-source.yml",
        "submission-broken-source.yml",
        "submission-machine-readable.yml",
    ):
        fields = template_fields(load_yaml(ISSUE_TEMPLATE_DIR / filename))
        assert fields["source_type"]["attributes"]["options"] == enum, filename


def test_machine_readable_surface_dropdowns_use_shorthand_vocabulary():
    for filename in SUBMISSION_TEMPLATES:
        fields = template_fields(load_yaml(ISSUE_TEMPLATE_DIR / filename))
        if "machine_readable_surface" not in fields:
            continue
        options = fields["machine_readable_surface"]["attributes"]["options"]
        assert options == MACHINE_READABLE_SURFACE_OPTIONS, filename


def test_submission_templates_state_claim_and_boundary_posture():
    for filename in SUBMISSION_TEMPLATES:
        text = (ISSUE_TEMPLATE_DIR / filename).read_text(encoding="utf-8")
        assert "claim, not a catalog change" in text, filename
        assert "enters verification" in text, filename
        assert "not legal conclusions" in text, filename
        assert "anti-bot bypass" in text, filename
        assert "Do not paste SOC reports" in text, filename
        assert "marked it as gated" in text, filename
        assert (
            "claim that enters verification, not a direct catalog change" in text
        ), filename
        assert (
            "I checked the existing catalog and open submissions for a duplicate."
            in text
        ), filename
        assert "This submission is factual public metadata only." in text, filename


def test_subprocessor_feed_form_distinguishes_feed_from_list():
    text = (ISSUE_TEMPLATE_DIR / "submission-subprocessor-feed.yml").read_text(
        encoding="utf-8"
    )
    assert "A feed is a notification or retrieval surface" in text
    assert "use New assurance source instead" in text


def test_submission_guide_states_intake_doctrine():
    assert SUBMISSION_GUIDE.exists()
    text = SUBMISSION_GUIDE.read_text(encoding="utf-8")

    assert "A submission is a claim. It does not change catalog data." in text
    assert "Submit public sources only" in text
    assert "Do not upload confidential reports" in text
    assert "Do not paste SOC reports, DPA contents, customer portal content" in text
    assert "Gated sources must be marked as gated" in text
    assert "OpenVA records public source metadata and provenance, not legal conclusions" in text
    assert "non-authoritative until verified" in text
    assert "contributor-facing shorthand" in text
    assert "Which form to use" in text


def test_submission_guide_is_registered_and_linked():
    assert "docs/submission-intake.md" in Path("docs/index.md").read_text(
        encoding="utf-8"
    )
    assert "docs/submission-intake.md" in Path("CONTRIBUTING.md").read_text(
        encoding="utf-8"
    )


def test_triage_policy_documents_submission_labels():
    text = Path("docs/triage-policy.md").read_text(encoding="utf-8")

    for label in [
        "submission:new-vendor",
        "submission:new-source",
        "submission:broken-source",
        "submission:vendor-identity",
        "submission:machine-readable",
        "submission:needs-triage",
    ]:
        assert label in text

    assert "Source claim submission" in text
    assert "non-authoritative until verified" in text
