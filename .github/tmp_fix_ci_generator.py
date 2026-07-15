from pathlib import Path

path = Path('.github/tmp_apply_ci_rationalization.py')
text = path.read_text(encoding='utf-8')
old = '''test_anchor = "          tests/test_workflow_operating_model.py\\n"
if validate.count(test_anchor) != 2:
    raise SystemExit(f"unexpected workflow test anchor count: {validate.count(test_anchor)}")
validate = validate.replace(
    test_anchor,
    test_anchor + "          tests/test_workflow_workspace_ci.py\\n",
)
'''
new = '''workflow_test_anchor = (
    "          tests/test_workflow_operating_model.py\\n"
    "          tests/test_workflow_retirement_evidence.py\\n"
)
workflow_test_replacement = (
    "          tests/test_workflow_operating_model.py\\n"
    "          tests/test_workflow_workspace_ci.py\\n"
    "          tests/test_workflow_retirement_evidence.py\\n"
)
shard_test_anchor = (
    "              tests/test_workflow_operating_model.py\\n"
    "              tests/test_workflow_retirement_evidence.py\\n"
)
shard_test_replacement = (
    "              tests/test_workflow_operating_model.py\\n"
    "              tests/test_workflow_workspace_ci.py\\n"
    "              tests/test_workflow_retirement_evidence.py\\n"
)
if workflow_test_anchor not in validate:
    raise SystemExit("workflow operating-model test anchor not found")
if shard_test_anchor not in validate:
    raise SystemExit("workflow regression-shard test anchor not found")
validate = validate.replace(workflow_test_anchor, workflow_test_replacement, 1)
validate = validate.replace(shard_test_anchor, shard_test_replacement, 1)
'''
if old not in text:
    raise SystemExit('generator indentation block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
