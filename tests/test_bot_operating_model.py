from pathlib import Path

import yaml

BOT_MODEL = Path("docs/operations/BOT_OPERATING_MODEL.md")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")

REQUIRED_FILES = [
    BOT_MODEL,
    BOT_AUTHORITY,
    BOT_FAILURE_TAXONOMY,
    BOT_QUEUE_POLICY,
]

AUTHORITY_REQUIRED_FIELDS = {
    "id",
    "status",
    "workflows",
    "may_write_branches",
    "may_open_prs",
    "may_label_prs",
    "may_enable_auto_merge",
    "may_merge_prs",
    "may_write_catalog_truth",
    "allowed_paths",
    "required_labels_for_write_authority",
    "token_permissions",
    "audit_artifacts",
    "deny_by_default",
}

REQUIRED_FAILURE_CODES = {
    "source_preflight_failure",
    "redirect_canonicalization_failure",
    "duplicate_url_failure",
    "terminology_contract_failure",
    "schema_validation_failure",
    "generated_drift_failure",
    "workflow_input_compatibility_failure",
    "automerge_lane_mismatch",
    "external_fetch_instability",
    "stale_evidence_failure",
    "permission_policy_denial",
}

FAILURE_REQUIRED_FIELDS = {
    "code",
    "summary",
    "retry_eligible",
    "retry_policy",
    "escalation_target",
    "open_or_update_hardening_issue",
    "defer_candidate",
    "stop_lane",
}

COMMAND_STRINGS = {
    "/openva retry-source-preflight",
    "/openva defer-candidate",
    "/openva promote-reviewed-plan",
    "/openva explain-strict-growth",
    "/openva quarantine-source",
    "/openva recheck-final-url",
    "/openva hold",
    "/openva unhold",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def authority_lanes() -> list[dict]:
    return load_yaml(BOT_AUTHORITY)["lanes"]


def lane_is_write_capable(lane: dict) -> bool:
    if any(
        lane[field]
        for field in (
            "may_write_branches",
            "may_open_prs",
            "may_label_prs",
            "may_enable_auto_merge",
            "may_merge_prs",
            "may_write_catalog_truth",
        )
    ):
        return True
    return any(value == "write" for value in lane["token_permissions"].values())


def test_required_bot_operating_model_files_exist():
    for path in REQUIRED_FILES:
        assert path.exists(), path


def test_bot_operating_model_yaml_contracts_parse_and_point_to_source_document():
    for path in (BOT_AUTHORITY, BOT_FAILURE_TAXONOMY, BOT_QUEUE_POLICY):
        contract = load_yaml(path)
        assert contract["source_document"] == "docs/operations/BOT_OPERATING_MODEL.md"


def test_authority_default_posture_denies_undeclared_lanes_and_write_paths():
    contract = load_yaml(BOT_AUTHORITY)

    assert contract["default_posture"]["undeclared_lanes_are_denied"] is True
    assert contract["default_posture"]["undeclared_write_paths_are_denied"] is True


def test_each_authority_lane_has_required_fields_and_write_authority_explanation():
    for lane in authority_lanes():
        assert AUTHORITY_REQUIRED_FIELDS <= set(lane), lane["id"]
        assert isinstance(lane["workflows"], list)
        assert isinstance(lane["allowed_paths"], list)
        assert isinstance(lane["required_labels_for_write_authority"], list)
        assert isinstance(lane["token_permissions"], dict)
        assert isinstance(lane["audit_artifacts"], list)

        if lane_is_write_capable(lane):
            assert lane["allowed_paths"] or lane.get("write_authority_explanation"), lane["id"]


def test_discovery_and_report_only_lanes_do_not_write_catalog_truth():
    lanes_by_id = {lane["id"]: lane for lane in authority_lanes()}

    assert lanes_by_id["catalog_growth_discovery"]["may_write_catalog_truth"] is False
    assert lanes_by_id["source_maintenance_report"]["may_write_catalog_truth"] is False
    assert lanes_by_id["catalog_quality"]["may_write_catalog_truth"] is False
    assert lanes_by_id["legacy_report"]["may_write_catalog_truth"] is False
    assert load_yaml(BOT_AUTHORITY)["default_posture"][
        "report_only_lanes_may_write_catalog_truth"
    ] is False
    assert load_yaml(BOT_AUTHORITY)["default_posture"][
        "discovery_lanes_may_write_catalog_truth"
    ] is False


def test_failure_taxonomy_includes_required_codes_and_behavior_fields():
    failure_classes = load_yaml(BOT_FAILURE_TAXONOMY)["failure_classes"]
    codes = {entry["code"] for entry in failure_classes}

    assert REQUIRED_FAILURE_CODES <= codes
    for entry in failure_classes:
        assert FAILURE_REQUIRED_FIELDS <= set(entry), entry["code"]
        assert isinstance(entry["retry_eligible"], bool)
        assert entry["retry_policy"]
        assert entry["escalation_target"]
        assert isinstance(entry["open_or_update_hardening_issue"], bool)
        assert isinstance(entry["defer_candidate"], bool)
        assert isinstance(entry["stop_lane"], bool)


def test_queue_policy_has_global_limits_and_stale_evidence_controls():
    global_policy = load_yaml(BOT_QUEUE_POLICY)["global"]

    assert global_policy["pause_switch_label"] == "openva-bot-paused"
    assert global_policy["max_open_catalog_growth_prs"] > 0
    assert global_policy["max_open_source_repair_prs"] > 0
    assert global_policy["max_bot_prs_per_day"] > 0
    assert global_policy["max_bot_prs_per_week"] > 0
    assert global_policy["cooldown_after_failure_hours"] > 0
    assert global_policy["stale_evidence_max_age_hours"]["strict_growth"] > 0
    assert global_policy["stale_evidence_max_age_hours"]["deterministic_outputs"] > 0


def test_queue_lane_ids_exist_in_authority_contract_and_have_positive_open_pr_limits():
    authority_lane_ids = {lane["id"] for lane in authority_lanes()}
    queue_lanes = load_yaml(BOT_QUEUE_POLICY)["lanes"]

    for lane in queue_lanes:
        assert lane["lane_id"] in authority_lane_ids
        assert isinstance(lane["max_open_prs"], int)
        assert lane["max_open_prs"] > 0


def test_write_capable_lanes_are_explicitly_declared_and_deny_by_default():
    for lane in authority_lanes():
        if lane_is_write_capable(lane):
            assert lane["id"]
            assert lane["deny_by_default"] is True


def test_bot_operating_model_mentions_all_failure_codes_and_commands():
    document = BOT_MODEL.read_text(encoding="utf-8")
    taxonomy_codes = {
        entry["code"] for entry in load_yaml(BOT_FAILURE_TAXONOMY)["failure_classes"]
    }

    for code in taxonomy_codes:
        assert code in document
    for command in COMMAND_STRINGS:
        assert command in document


def test_bot_authority_workflows_exist_in_workflow_inventory():
    inventory = load_yaml(WORKFLOW_INVENTORY)
    inventory_names = {entry["name"] for entry in inventory["public_workflows"]}

    for lane in authority_lanes():
        for workflow_name in lane["workflows"]:
            assert workflow_name in inventory_names, (lane["id"], workflow_name)
