from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import yaml

from tools.openva.bot_dashboard import make_signal, render_dashboard, sort_signals, write_dashboard

BOT_DASHBOARD_SIGNAL_QUALITY_DOC = Path("docs/operations/BOT_DASHBOARD_SIGNAL_QUALITY.md")
BOT_DASHBOARD_CONTRACT = Path("docs/operations/contracts/bot-dashboard.yaml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
BOT_DASHBOARD_DOC = Path("docs/operations/BOT_DASHBOARD.md")
BOT_OBSERVABILITY_CONTRACT = Path("docs/operations/contracts/bot-observability.yaml")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")

EXPECTED_SIGNAL_CLASSES = {
    "blocking",
    "action_required",
    "watch",
    "informational",
    "missing_optional_input",
    "unknown",
}

EXPECTED_PRIORITY_ORDER = [
    "queue_pause_or_denial",
    "failure_router_stop_lane",
    "unsafe_chatops_denial",
    "workflow_retirement_blocker",
    "queue_deferral",
    "retryable_failure",
    "ignored_chatops_comment",
    "future_retirement_candidate",
]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_dashboard_contracts(tmp_path: Path) -> None:
    docs_contracts = tmp_path / "docs/operations/contracts"
    docs_contracts.mkdir(parents=True)
    for path in (BOT_AUTHORITY, BOT_FAILURE_TAXONOMY, BOT_QUEUE_POLICY, BOT_DASHBOARD_CONTRACT):
        shutil.copy2(path, docs_contracts / path.name)


def test_signal_quality_doc_exists_and_declares_no_authority_expansion():
    assert BOT_DASHBOARD_SIGNAL_QUALITY_DOC.exists()
    text = BOT_DASHBOARD_SIGNAL_QUALITY_DOC.read_text(encoding="utf-8")

    assert "WP24 improves dashboard readability without increasing bot authority" in text
    assert "does not" in text
    assert "Signal Quality Summary" in text


def test_signal_classes_are_declared_in_contract():
    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    classes = {entry["id"] for entry in contract["signal_classes"]}
    ranks = [entry["rank"] for entry in contract["signal_classes"]]

    assert EXPECTED_SIGNAL_CLASSES == classes
    assert len(ranks) == len(set(ranks))
    assert contract["signal_rendering"]["missing_optional_inputs_are_not_blocking"] is True
    assert contract["signal_rendering"]["blocking_signals_sort_before_informational"] is True


def test_priority_model_declares_required_signal_order_without_authority_expansion():
    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    priority_model = contract["priority_model"]
    entries = priority_model["ordering"]

    assert [entry["id"] for entry in entries] == EXPECTED_PRIORITY_ORDER
    assert [entry["rank"] for entry in entries] == list(range(len(EXPECTED_PRIORITY_ORDER)))
    assert priority_model["missing_optional_input_class"] == "missing_optional_input"
    assert priority_model["required_input_missing_class"] == "blocking"
    assert priority_model["unknown_signal_class"] == "unknown"
    assert {entry["class"] for entry in entries} <= EXPECTED_SIGNAL_CLASSES
    assert load_yaml(BOT_DASHBOARD_CONTRACT)["dashboard_issue"]["create_or_update_enabled"] is False


def test_priority_model_documents_wp24_required_ordering():
    doc = BOT_DASHBOARD_DOC.read_text(encoding="utf-8")

    assert "## Priority Model" in doc
    assert doc.index("Queue pauses, queue denials") < doc.index("Failure-router stop-lane")
    assert doc.index("Failure-router stop-lane") < doc.index("Denied or unsafe chat-ops")
    assert doc.index("Denied or unsafe chat-ops") < doc.index("Workflow-retirement blockers")
    assert doc.index("Workflow-retirement blockers") < doc.index("Missing optional local artifacts")
    assert "does not activate labels" in doc
    assert "retire workflows" in doc


def test_signal_quality_summary_is_in_docs_contract_and_rendered_markdown():
    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    doc = BOT_DASHBOARD_DOC.read_text(encoding="utf-8")
    rendered = render_dashboard()

    assert {section["id"] for section in contract["expected_sections"]} >= {"signal_quality_summary"}
    assert "Signal Quality Summary" in doc
    assert "## Signal Quality Summary" in rendered


def test_all_rendered_signal_classes_are_known():
    rendered = render_dashboard()
    known = {entry["id"] for entry in load_yaml(BOT_DASHBOARD_CONTRACT)["signal_classes"]}

    for line in rendered.splitlines():
        if line.startswith("| `") and " | " in line and not line.startswith("| `source"):
            possible_class = line.split("`")[1]
            if possible_class in EXPECTED_SIGNAL_CLASSES:
                assert possible_class in known


def test_blocking_signals_sort_before_informational_signals():
    contract = load_yaml(BOT_DASHBOARD_CONTRACT)
    signals = [
        make_signal("informational", "Info", "context", "keep watching"),
        make_signal("missing_optional_input", "Missing", "optional input missing", "do not block"),
        make_signal("blocking", "Blocker", "must stop", "resolve blocker"),
        make_signal("action_required", "Action", "review needed", "review item"),
        make_signal("watch", "Watch", "monitor", "refresh evidence"),
    ]

    ordered = sort_signals(signals, contract)

    assert [entry["class"] for entry in ordered] == [
        "blocking",
        "action_required",
        "watch",
        "informational",
        "missing_optional_input",
    ]


def test_missing_optional_artifacts_do_not_create_false_critical_posture(tmp_path):
    copy_dashboard_contracts(tmp_path)
    rendered = render_dashboard(tmp_path)

    assert "## Signal Quality Summary" in rendered
    assert "`missing_optional_input`" in rendered
    assert "Optional local artifacts missing" in rendered
    assert "`blocking` | Required dashboard input missing" not in rendered


def test_next_safe_action_is_deterministic():
    assert render_dashboard() == render_dashboard()
    assert "## Next Safe Action" in render_dashboard()


def test_dashboard_output_is_deterministic_with_missing_artifacts(tmp_path):
    copy_dashboard_contracts(tmp_path)

    assert render_dashboard(tmp_path) == render_dashboard(tmp_path)


def test_observability_scorecard_contract_still_builds_with_signal_quality_context():
    contract = load_yaml(BOT_OBSERVABILITY_CONTRACT)

    assert contract["contract"] == "bot-observability"
    assert "input_reports" in contract


def test_renderer_does_not_modify_catalog_data(tmp_path):
    before = data_vendor_digest()
    out = tmp_path / "bot-dashboard.md"

    write_dashboard(output_path=out)

    assert out.exists()
    assert data_vendor_digest() == before


def test_deprecated_terminology_is_not_introduced():
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])
    paths = [
        BOT_DASHBOARD_SIGNAL_QUALITY_DOC,
        BOT_DASHBOARD_DOC,
        BOT_DASHBOARD_CONTRACT,
        Path("tools/openva/bot_dashboard.py"),
        Path("tests/test_bot_dashboard_signal_quality.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for term in deprecated_terms:
        assert term not in combined
