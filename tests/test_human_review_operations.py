from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_human_review_operations_doc_exists_and_names_surfaces():
    text = read("docs/human-review-operations.md")

    assert "GitHub Actions artifacts" in text
    assert "Markdown reports" in text
    assert "JSON reports" in text
    assert "GitHub issues" in text
    assert "GitHub pull requests" in text
    assert "local CLI commands" in text


def test_human_review_operations_defers_dedicated_ui():
    text = read("docs/human-review-operations.md")

    assert "A separate UI is not required for the current OpenVA maturity level." in text
    assert "No separate UI yet." in text
    assert "Revisit when review volume" in text


def test_human_review_operations_defines_roles_and_states():
    text = read("docs/human-review-operations.md")

    for role in [
        "Source reviewer",
        "Language reviewer",
        "Catalog reviewer",
        "Workflow reviewer",
        "Release reviewer",
    ]:
        assert role in text

    for state in [
        "accepted",
        "needs-source-update",
        "needs-language-review",
        "needs-workflow-update",
        "needs-workflow-consolidation",
        "blocked-gated-source",
        "blocked-unsafe-url",
        "non-blocking-source-quality",
        "release-blocker",
    ]:
        assert state in text


def test_human_review_operations_preserves_release_blockers():
    text = read("docs/human-review-operations.md")

    for blocker in [
        "unsafe URLs",
        "policy violations",
        "advisory language",
        "generated-file drift",
        "schema or pack incompatibility",
        "release smoke failure",
        "conformance fixture failure",
    ]:
        assert blocker in text


def test_human_review_operations_defines_workflow_lifecycle():
    text = read("docs/human-review-operations.md")

    for decision in ["Create", "Update", "Consolidate", "Delete"]:
        assert decision in text

    assert "scheduled workflows are non-mutating by default" in text
    assert "write-capable workflows create PRs rather than changing `main`" in text
    assert "catalog mutation without a PR" in text


def test_docs_index_links_review_operations_docs():
    text = read("docs/index.md")

    assert "docs/human-review-operations.md" in text
    assert "docs/source-refinement-workflow.md" in text
    assert "docs/observation-reporting.md" in text
    assert "docs/agent-control-plane.md" in text
    assert "docs/agent-runbook.md" in text
