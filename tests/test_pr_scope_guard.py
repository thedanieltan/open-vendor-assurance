"""Tests for the PR work-package scope guard (tools/openva/pr_scope_guard.py).

WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01 item 5: a guard comparing a PR's changed paths
against its declared work-package scope, so unrelated ancestor work cannot silently
enter a PR. These test the pure matching logic, the committed manifest's
well-formedness, and — as a dogfood — that the guard WOULD have flagged the exact
PR #400 contamination.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.openva.pr_scope_guard import (
    DeclarationError,
    allowed_globs,
    declared_work_package,
    load_manifest,
    out_of_scope_paths,
)

ROOT = Path(__file__).resolve().parents[1]

_MANIFEST = {
    "version": 1,
    "shared_allowed": ["docs/operations/contracts/work-package-scope.yaml"],
    "work_packages": {
        "WP-A": {"allowed_paths": ["tools/a/*", "tests/test_a.py"]},
        "WP-B": {"allowed_paths": ["docs/b.md"]},
    },
}


def test_in_scope_paths_pass():
    changed = ["tools/a/x.py", "tools/a/nested/y.py", "tests/test_a.py"]
    assert out_of_scope_paths(changed, "WP-A", _MANIFEST) == []


def test_out_of_scope_paths_are_flagged():
    changed = ["tools/a/x.py", "docs/b.md", "tools/c/z.py"]
    # docs/b.md belongs to WP-B; tools/c/z.py belongs to no declared scope.
    assert out_of_scope_paths(changed, "WP-A", _MANIFEST) == ["docs/b.md", "tools/c/z.py"]


def test_shared_paths_are_always_in_scope():
    changed = ["docs/operations/contracts/work-package-scope.yaml", "tools/a/x.py"]
    assert out_of_scope_paths(changed, "WP-A", _MANIFEST) == []


def test_unknown_work_package_raises():
    with pytest.raises(KeyError):
        allowed_globs(_MANIFEST, "WP-DOES-NOT-EXIST")
    with pytest.raises(KeyError):
        out_of_scope_paths(["tools/a/x.py"], "WP-DOES-NOT-EXIST", _MANIFEST)


def test_star_glob_spans_path_separators():
    # `dir/*` must match nested files (fnmatchcase: * spans '/').
    assert out_of_scope_paths(["tools/a/deep/deeper/z.py"], "WP-A", _MANIFEST) == []


# --- committed manifest ------------------------------------------------------


def test_committed_manifest_is_well_formed():
    manifest = load_manifest()
    assert manifest["version"] == 1
    assert isinstance(manifest["shared_allowed"], list) and manifest["shared_allowed"]
    wps = manifest["work_packages"]
    assert isinstance(wps, dict) and wps
    for wp_id, body in wps.items():
        assert wp_id.startswith("WP-"), wp_id
        assert body.get("allowed_paths"), f"{wp_id} must declare allowed_paths"
        assert isinstance(body["allowed_paths"], list)


def test_this_ratification_prs_files_are_in_its_declared_scope():
    # Dogfood: every file this ratification PR changes must be within its own declared
    # scope (the guard passes on itself).
    manifest = load_manifest()
    this_pr_paths = [
        # Evidence + regression tests.
        "docs/operations/legal-entity-export-ratification.md",
        "tests/test_legal_entity_export_ratification.py",
        # Required corrections (findings 2/3 + non-blocking docstring) and their tests.
        "adapters/python/openva_vendor_inventory_matcher/openva_vendor_inventory_matcher/core.py",
        "tools/openva/agent_export.py",
        "integrations/mcp/openva_mcp/openva_mcp/matching.py",
        "tests/test_agent_export.py",
        # CI enforcement of the guard (findings 1/4).
        ".github/workflows/pr-scope-guard.yml",
        "docs/operations/contracts/workflow-inventory.yaml",
        # The scope machinery itself (shared_allowed).
        "docs/operations/contracts/work-package-scope.yaml",
        "tools/openva/pr_scope_guard.py",
        "tests/test_pr_scope_guard.py",
        "docs/operations/pr-scope-guard.md",
    ]
    assert out_of_scope_paths(this_pr_paths, "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01", manifest) == []


# --- work-package declaration (fail-closed) ----------------------------------


def test_declared_work_package_accepts_exactly_one():
    body = "Some PR description.\n\nWork-Package: WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01\n\nMore text."
    assert declared_work_package(body) == "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01"


def test_declared_work_package_fails_closed_on_zero():
    with pytest.raises(DeclarationError):
        declared_work_package("A PR body with no declaration line.")


def test_declared_work_package_fails_closed_on_multiple():
    body = "Work-Package: WP-ONE\nWork-Package: WP-TWO\n"
    with pytest.raises(DeclarationError):
        declared_work_package(body)


def test_declared_work_package_repeated_same_id_is_one():
    body = "Work-Package: WP-ONE\n...\nWork-Package: WP-ONE\n"
    assert declared_work_package(body) == "WP-ONE"


def test_guard_would_have_caught_pr_400_contamination():
    # The exact failure: PR #400 (candidate-activation) inherited the legal-entity
    # commit, so its changed set spanned BOTH work packages. Declared as the
    # candidate-activation WP, the legal-entity files must be flagged out of scope.
    manifest = load_manifest()
    candidate_paths = [
        "tools/openva/candidate_record.py",
        "tools/openva/vendor_resolution.py",
        "config/automerge-policy.yaml",
    ]
    legal_entity_paths = [
        "tools/openva/agent_export.py",
        "adapters/python/openva_vendor_inventory_matcher/openva_vendor_inventory_matcher/core.py",
        "integrations/mcp/openva_mcp/openva_mcp/matching.py",
        "schemas/openva/agent-export.schema.json",
    ]
    violations = out_of_scope_paths(
        candidate_paths + legal_entity_paths, "WP-OPENVA-CANDIDATE-ACTIVATION-01", manifest
    )
    assert set(violations) == set(legal_entity_paths), (
        "the guard must flag the legal-entity files as outside the candidate-activation scope"
    )
    # And those same files ARE in scope for the legal-entity work package.
    assert out_of_scope_paths(legal_entity_paths, "WP-OPENVA-AI-NATIVE-DISTRIBUTION-LEGAL-ENTITY", manifest) == []
