from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "maintenance" / "operator-runbook.md"


def test_maintenance_operator_runbook_exists_and_covers_required_operations():
    text = RUNBOOK.read_text(encoding="utf-8")
    lower_text = text.lower()

    required_phrases = [
        "catalog-maintenance-pr",
        "maintenance/reviewed",
        "promotion-plan-cleanup",
        "No catalog maintenance changes produced",
        "Allow GitHub Actions to create and approve pull requests",
        "no candidate auto-promotion",
        "no raw vendor document mirrored",
        "non_advisory",
    ]

    for phrase in required_phrases:
        assert phrase.lower() in lower_text
