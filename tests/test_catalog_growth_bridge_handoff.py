from pathlib import Path


BRIDGE = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
AUTOMERGE = Path(".github/workflows/agent-automerge.yml")

GENERATED_CATALOG_TITLE = "Catalog: apply reviewed candidate source promotion"


def test_bridge_dispatches_pr_title_owned_by_generated_catalog_automerge_lane():
    bridge = BRIDGE.read_text(encoding="utf-8")
    automerge = AUTOMERGE.read_text(encoding="utf-8")

    dispatch_block = bridge[
        bridge.index("- name: Dispatch existing strict-growth promotion workflow") :
        bridge.index("- name: Upload promotion bridge decision artifacts")
    ]
    generated_catalog_condition = automerge[
        automerge.index("generated-catalog:") : automerge.index("generated-catalog-rereview:")
    ]

    assert f'pr_title={GENERATED_CATALOG_TITLE}' in dispatch_block
    assert f"title == '{GENERATED_CATALOG_TITLE}'" in generated_catalog_condition
    assert "Catalog: strict-growth promotion bridged from discovery run" not in dispatch_block


def test_bridge_does_not_widen_automerge_authority_with_labels():
    bridge = BRIDGE.read_text(encoding="utf-8")
    dispatch_block = bridge[
        bridge.index("- name: Dispatch existing strict-growth promotion workflow") :
        bridge.index("- name: Upload promotion bridge decision artifacts")
    ]

    assert "automerge:strict-growth" not in dispatch_block
    assert "catalog-growth" not in dispatch_block
    assert "gh pr edit" not in dispatch_block
