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
    allowed_globs,
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
    # Dogfood: every file this ratification PR adds must be within its own declared scope.
    manifest = load_manifest()
    this_pr_paths = [
        "docs/operations/legal-entity-export-ratification.md",
        "tests/test_legal_entity_export_ratification.py",
        # The scope machinery is shared_allowed.
        "docs/operations/contracts/work-package-scope.yaml",
        "tools/openva/pr_scope_guard.py",
        "tests/test_pr_scope_guard.py",
        "docs/operations/pr-scope-guard.md",
    ]
    assert out_of_scope_paths(this_pr_paths, "WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01", manifest) == []


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
