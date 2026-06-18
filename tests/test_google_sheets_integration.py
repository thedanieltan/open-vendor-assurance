"""Contract tests for the Google Sheets enrichment integration (integrations/google-sheets).

These assert the integration's static guarantees from Python so they run in the existing
pytest suite, and execute the JavaScript pure-function tests via ``node --test`` when a
Node runtime is available (skipped otherwise). They do not weaken any existing suite.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "google-sheets"
SRC = INTEGRATION / "src"

GS_FILES = sorted(SRC.glob("*.gs"))

# Every file a user must create when installing into a bound Apps Script project. A shipped
# Apps Script/HTML dependency that the menu loads at runtime must appear here (and in the
# README install steps) so it can never be silently omitted again.
REQUIRED_MANUAL_INSTALL_FILES = (
    "src/Core.gs",
    "src/ApiClient.gs",
    "src/SheetAdapter.gs",
    "src/Menu.gs",
    "src/Help.html",
    "src/SourceTypes.html",
    "appsscript.json",
)


def _all_gs_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in GS_FILES)


# --------------------------------------------------------------------------- layout


def test_integration_files_exist():
    assert INTEGRATION.is_dir()
    for name in ("appsscript.json", "README.md"):
        assert (INTEGRATION / name).is_file(), name
    for name in ("Core.gs", "ApiClient.gs", "SheetAdapter.gs", "Menu.gs"):
        assert (SRC / name).is_file(), name
    assert (INTEGRATION / "test" / "core.test.mjs").is_file()
    assert GS_FILES, "expected at least one .gs source file"


def test_required_manual_install_files_exist_and_are_documented():
    # Every required file ships ...
    for rel in REQUIRED_MANUAL_INSTALL_FILES:
        assert (INTEGRATION / rel).is_file(), rel
    # ... and is named in the README's manual-install steps, including HTML dialogs the
    # menu loads at runtime (e.g. SourceTypes.html for "Configure source types"), so the
    # documented install path cannot omit a runtime dependency.
    install_section = (INTEGRATION / "README.md").read_text(encoding="utf-8")
    assert "Create a bound Apps Script project" in install_section
    for rel in REQUIRED_MANUAL_INSTALL_FILES:
        name = Path(rel).name
        assert name in install_section, name
    # Cross-check: any HTML file the menu loads via createHtmlOutputFromFile must be in the
    # required set, so a newly added dialog is caught here too.
    menu = (SRC / "Menu.gs").read_text(encoding="utf-8")
    for loaded in re.findall(r"createHtmlOutputFromFile\(['\"]([A-Za-z0-9_]+)['\"]\)", menu):
        assert f"src/{loaded}.html" in REQUIRED_MANUAL_INSTALL_FILES, loaded


# --------------------------------------------------------------------------- manifest / scopes


def test_appsscript_manifest_uses_v8_and_minimal_scopes():
    manifest = json.loads((INTEGRATION / "appsscript.json").read_text(encoding="utf-8"))
    assert manifest["runtimeVersion"] == "V8"
    scopes = set(manifest.get("oauthScopes", []))
    assert scopes == {
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
        "https://www.googleapis.com/auth/script.external_request",
        "https://www.googleapis.com/auth/script.container.ui",
    }


def test_no_broad_or_unrelated_scopes_requested():
    manifest = (INTEGRATION / "appsscript.json").read_text(encoding="utf-8")
    forbidden = [
        "auth/gmail",
        "auth/calendar",
        "auth/contacts",
        "auth/drive",  # drive-wide; current-document spreadsheet scope is used instead
        "auth/userinfo",
        "auth/admin",
        "auth/spreadsheets\"",  # full (non current-only) spreadsheets scope
    ]
    for token in forbidden:
        assert token not in manifest, token


# --------------------------------------------------------------------------- secrets / ids


def test_no_api_key_or_bearer_token_embedded():
    text = _all_gs_text() + (INTEGRATION / "README.md").read_text(encoding="utf-8")
    # No bearer/authorization scheme and no api-key assignment is present anywhere.
    assert "Bearer " not in text
    assert "Authorization" not in text
    assert not re.search(r"api[_-]?key\s*[:=]\s*['\"]", text, re.IGNORECASE)


def test_no_real_clasp_script_id_committed():
    assert not (INTEGRATION / ".clasp.json").exists(), "a real .clasp.json must not be committed"
    example = INTEGRATION / ".clasp.example.json"
    if example.exists():
        data = json.loads(example.read_text(encoding="utf-8"))
        assert "REPLACE" in data.get("scriptId", "").upper()


def test_no_hardcoded_production_endpoint():
    # The base URL is configured at runtime; no host-bearing /v1 endpoint is baked in.
    assert not re.search(r"https://[A-Za-z0-9.\-]+/v1/", _all_gs_text())


# --------------------------------------------------------------------------- privacy / logging


def test_no_request_logging_in_source():
    text = _all_gs_text()
    assert "Logger.log" not in text
    assert "console.log" not in text


def test_no_custom_network_spreadsheet_formula():
    # No @customfunction custom function (which would create a per-cell network formula).
    assert "@customfunction" not in _all_gs_text()


# --------------------------------------------------------------------------- API surface


def test_only_catalog_meta_and_enrich_endpoints_are_called():
    paths = set(re.findall(r"/v1/[A-Za-z0-9/_{}]+", _all_gs_text()))
    assert paths <= {"/v1/catalog/meta", "/v1/enrich"}, paths
    assert "/v1/enrich" in paths
    assert "/v1/catalog/meta" in paths


def test_source_type_selection_supported():
    core = (SRC / "Core.gs").read_text(encoding="utf-8")
    # The exact canonical API vocabulary is present, plus the config key and validators.
    for token in (
        "OPENVA_SOURCE_TYPES_KEY",
        "OPENVA_SUPPORTED_SOURCE_TYPES",
        "normalizeSourceTypes",
        "resolveStoredSourceTypes",
    ):
        assert token in core, token
    for source_type in (
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "security_page",
        "trust_center",
        "compliance_page",
    ):
        assert source_type in core, source_type
    # The enrich request includes source_types, and a config menu item exists.
    assert "source_types" in (SRC / "ApiClient.gs").read_text(encoding="utf-8")
    assert "Configure source types" in (SRC / "Menu.gs").read_text(encoding="utf-8")


def test_document_lock_guards_enrichment():
    adapter = (SRC / "SheetAdapter.gs").read_text(encoding="utf-8")
    assert "LockService.getDocumentLock" in adapter
    assert "tryLock" in adapter
    assert "releaseLock" in adapter
    # The lock contract is factored into a finally-releasing helper in Core.gs.
    core = (SRC / "Core.gs").read_text(encoding="utf-8")
    assert "withDocumentLock" in core
    assert "finally" in core


def test_no_broad_scope_added_for_locking_or_dialogs():
    # Locking and HTML dialogs must not have introduced a broader scope.
    manifest = json.loads((INTEGRATION / "appsscript.json").read_text(encoding="utf-8"))
    assert set(manifest["oauthScopes"]) == {
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
        "https://www.googleapis.com/auth/script.external_request",
        "https://www.googleapis.com/auth/script.container.ui",
    }


def test_distribution_language_is_accurate():
    readme = (INTEGRATION / "README.md").read_text(encoding="utf-8")
    flat = " ".join(readme.split())  # collapse line wraps for phrase matching
    assert "No local Python, Docker, repository checkout or API secret is required." in flat
    assert "manual installation into a bound Apps Script project" in flat
    assert "not yet available" in flat
    # "zero-install" and "one-click" only appear as future objectives or explicit
    # negations, never as a current availability claim.
    for line in readme.lower().splitlines():
        if "zero-install" in line:
            assert "future" in line, line
        if "one-click" in line or "one click" in line:
            assert "no one-click" in line or "future" in line, line


def test_stable_openva_projection_headers_present():
    core = (SRC / "Core.gs").read_text(encoding="utf-8")
    for column in (
        "openva_match_status",
        "openva_vendor_id",
        "openva_vendor_name",
        "openva_dpa",
        "openva_subprocessors",
        "openva_privacy_notice",
        "openva_security",
        "openva_trust_center",
        "openva_compliance",
        "openva_last_observed_at",
        "openva_snapshot_digest",
        "openva_notes",
    ):
        assert column in core, column


# --------------------------------------------------------------------------- no office files


def test_no_microsoft_office_files_introduced():
    office_suffixes = {".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pptx"}
    offending = [p for p in INTEGRATION.rglob("*") if p.suffix.lower() in office_suffixes]
    assert offending == [], offending


# --------------------------------------------------------------------------- node tests


def test_node_pure_function_tests_pass():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node runtime not available")
    test_files = sorted((INTEGRATION / "test").glob("*.test.mjs"))
    assert test_files, "expected at least one Node test file"
    result = subprocess.run(
        [node, "--test", *[str(p.relative_to(ROOT)) for p in test_files]],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
