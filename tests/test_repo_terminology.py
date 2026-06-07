from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TERMINOLOGY_DOC = ROOT / "docs" / "architecture" / "OPENVA_TERMINOLOGY.md"
TERMINOLOGY_CONTRACT = ROOT / "docs" / "operations" / "contracts" / "repo-terminology.yaml"
CANDIDATE_PROMOTION_WORKFLOW = ROOT / ".github" / "workflows" / "candidate-promotion-pr.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_terminology_doc_exists_and_defines_core_terms():
    assert TERMINOLOGY_DOC.exists()
    text = read(TERMINOLOGY_DOC)

    for term in [
        "canonical catalog",
        "staging / candidate layer",
        "review evidence",
        "source maintenance",
        "generated exports",
        "publication layer",
        "source record",
        "source role",
        "coverage claim",
        "source verification",
        "source preflight",
        "source health",
        "strict-growth eligibility",
        "strict-growth promotion plan",
        "selected promotion action",
        "deferred action",
        "max_promotion_actions_per_pr",
        "strict-growth-latest",
        "automerge:strict-growth",
        "machine-canonical",
        "P0 source repair",
    ]:
        assert term in text


def test_terminology_doc_guides_agent_normalization_without_replacing_architecture_authority():
    text = read(TERMINOLOGY_DOC)

    assert "repository terminology guide for AI agents and maintainers" in text
    assert "OPENVA_SYSTEM_DESIGN.md`, which remains the architecture authority" in text
    assert "prevent semantic drift" in text
    assert "Humans may provide context in non-canonical language" in text
    assert "Agents must normalize that context" in text
    assert "Do not copy informal prompt wording into repository artifacts" in text
    assert "## Agent normalization rule" in text
    assert "Human may say" in text
    assert "Agent should implement as" in text


def test_machine_readable_terminology_contract_exists_and_validates():
    assert TERMINOLOGY_CONTRACT.exists()
    data = yaml.safe_load(read(TERMINOLOGY_CONTRACT))

    assert data["schema_version"] == "0.1.0"
    assert "preferred_terms" in data
    assert "deprecated_terms" in data
    assert "max_promotion_actions_per_pr" in data["preferred_terms"]
    assert "max_actions_per_plan" in data["deprecated_terms"]
    assert data["deprecated_terms"]["max_actions_per_plan"]["replacement"] == "max_promotion_actions_per_pr"
    assert "compatibility input" in data["deprecated_terms"]["max_actions_per_plan"]["allowed_contexts"]


def test_deprecated_batch_limit_alias_is_documented_as_compatibility_only():
    doc = read(TERMINOLOGY_DOC)
    contract = yaml.safe_load(read(TERMINOLOGY_CONTRACT))

    assert "max_actions_per_plan" in doc
    assert "deprecated alias" in doc
    assert "not the full promotion plan" in doc
    allowed = set(contract["deprecated_terms"]["max_actions_per_plan"]["allowed_contexts"])
    assert allowed <= {
        "compatibility input",
        "compatibility resolver",
        "compatibility test",
        "deprecated alias documentation",
        "legacy fixture",
    }


def test_candidate_promotion_workflow_exposes_preferred_batch_limit_input():
    workflow = read(CANDIDATE_PROMOTION_WORKFLOW)

    assert "max_promotion_actions_per_pr:" in workflow
    assert "Maximum selected promotion actions to apply in one generated Catalog PR." in workflow
    assert "Deprecated compatibility alias for max_promotion_actions_per_pr" in workflow
    assert "REQUESTED_MAX_PROMOTION_ACTIONS_PER_PR" in workflow
    assert "MAX_PROMOTION_ACTIONS_PER_PR" in workflow


def test_generated_pr_body_uses_selected_and_deferred_promotion_action_language():
    workflow = read(CANDIDATE_PROMOTION_WORKFLOW)

    assert "Promotion actions selected for this PR" in workflow
    assert "Max promotion actions per generated PR" in workflow
    assert "Strict-growth uncapped promotion actions" in workflow
    assert "Strict-growth source-health screened promotion actions" in workflow
    assert "Strict-growth policy-capped promotion actions" in workflow
    assert "Strict-growth batch-deferred promotion actions" in workflow
    assert "Deferred actions" in workflow
    assert "Max actions per generated PR" not in workflow


def test_strict_growth_generation_and_automerge_lane_are_distinct_terms():
    doc = read(TERMINOLOGY_DOC)
    workflow = read(CANDIDATE_PROMOTION_WORKFLOW)

    assert "strict-growth-latest**: generation mode" in doc
    assert "it does not merge by itself" in doc
    assert "automerge:strict-growth**: explicit automerge label/lane" in doc
    assert "strict-growth-latest generation" in workflow
    assert "automerge:strict-growth" in workflow


def test_source_quality_and_coverage_terms_are_distinct():
    doc = read(TERMINOLOGY_DOC)
    contract = yaml.safe_load(read(TERMINOLOGY_CONTRACT))

    for term in ["source_verification", "source_preflight", "source_health", "source_record", "coverage_claim"]:
        assert term in contract["preferred_terms"]

    assert "Source verification**: network/source observation and classification" in doc
    assert "Source preflight**: blocking check over changed canonical source records" in doc
    assert "Source health**: broader longitudinal operating posture" in doc
    assert "Source record**: a public page or document location" in doc
    assert "Coverage claim**: explicit source-role coverage" in doc
    assert "Source count is not a proxy for full source-role coverage" in doc
