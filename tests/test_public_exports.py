import json
import re
from pathlib import Path

import yaml

from tools.openva.agent_export import build_agent_exports
from tools.openva.contribution_intake import ADVISORY_RE

SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}

COMMIT_SHA = "testsha0000000000000000000000000000000000"
GENERATED_AT = "2026-06-12T00:00:00Z"


def build_real_repo_exports(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    build_agent_exports(
        out_dir=out,
        commit_sha=COMMIT_SHA,
        generated_at=GENERATED_AT,
    )
    return out


def all_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys |= all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            keys |= all_keys(nested)
    return keys


def test_exports_build_from_the_real_catalog_and_committed_ledger(tmp_path):
    out = build_real_repo_exports(tmp_path)
    index = json.loads((out / "openva-agent-index.json").read_text(encoding="utf-8"))
    vendors_index = json.loads((out / "vendors/index.json").read_text(encoding="utf-8"))

    catalog_vendor_count = len(list(Path("data/vendors").glob("*/vendor.yaml")))
    assert vendors_index["count"] == catalog_vendor_count
    assert index["counts"]["vendors"] == catalog_vendor_count
    assert len(index["vendor_exports"]) == catalog_vendor_count

    # The committed ledger is seeded, so without a run artifact the build
    # uses the explicitly marked fallback.
    assert index["observation_input"] == "committed_events_fallback"
    changes = json.loads((out / "changes/latest.json").read_text(encoding="utf-8"))
    assert changes["count"] > 0


def test_exports_contain_no_advisory_vocabulary_or_self_certifying_fields(tmp_path):
    out = build_real_repo_exports(tmp_path)
    for path in sorted(out.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        keys = all_keys(document)
        assert not (keys & SELF_CERTIFYING_FIELDS), path.name
        text = json.dumps(document)
        assert not ADVISORY_RE.search(text), (path.name, ADVISORY_RE.search(text))


def test_site_pages_workflow_builds_exports_after_site_build_and_stays_read_only():
    path = Path(".github/workflows/site-pages.yml")
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    triggers = workflow.get("on") or workflow.get(True) or {}

    # Inventory shape unchanged: same triggers, same permissions.
    assert set(triggers.keys()) == {"push", "workflow_dispatch"}
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pages": "write",
        "id-token": "write",
    }

    # Exports are built into the Pages artifact dir AFTER the site build.
    assert "--out site/dist/public" in text
    assert text.index("python site/build.py --out site/dist") < text.index("tools.openva.agent_export build")
    assert "source-health-artifacts/observation-ledger/latest-observations.json" in text
    assert "source-health-artifacts/observation-ledger/source-freshness-report.json" in text

    # No new write paths.
    assert "git commit" not in text
    assert "git push" not in text
    assert "create-pull-request" not in text


def test_gitignore_covers_publish_time_artifact_dirs():
    text = Path(".gitignore").read_text(encoding="utf-8")
    for entry in [
        "public/",
        "source-health-artifacts/",
        "coverage-audit-artifacts/",
        ".tmp-public/",
        ".tmp-agent-exports/",
        ".tmp-openva/",
        ".openva-submission/",
        ".openva-observation-ledger/",
    ]:
        assert re.search(rf"^{re.escape(entry)}$", text, flags=re.MULTILINE), entry
    # Source-of-truth paths must never be ignored.
    for forbidden in ["data/", "indexes/", "schemas/", "maintenance/"]:
        assert not re.search(rf"^{re.escape(forbidden)}$", text, flags=re.MULTILINE), forbidden


def test_contract_doc_states_doctrine_and_exclusions():
    text = Path("docs/agent-export-contract.md").read_text(encoding="utf-8")

    assert "does not version vendor truth" in text
    assert "schema_version" in text
    assert "commit_sha" in text
    assert "sha256" in text
    assert "No hosted API" in text or "no hosted API" in text or "No API" in text
    assert "MCP server" in text
    assert "risk scores" in text or "risk scoring" in text
    assert "Null means not yet observed" in text
    assert "committed_events_fallback" in text
    assert "docs/agent-export-contract.md" in Path("docs/index.md").read_text(encoding="utf-8")
