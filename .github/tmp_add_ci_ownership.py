from pathlib import Path

path = Path('.github/validation-ownership.yaml')
text = path.read_text(encoding='utf-8')

status_anchor = '''  - validate / repository-integrity
  - validate / workspace-affected-tests
'''
status_replacement = '''  - validate / repository-integrity
  - validate / workspace-plan
  - validate / workspace-component-tests
  - validate / workspace-affected-tests
'''
if status_anchor not in text:
    raise SystemExit('workspace required-context anchor not found')
text = text.replace(status_anchor, status_replacement, 1)

old_workspace = '''  workspace-affected-tests:
    owner_loop: workspace_control_plane
    purpose: Validate the workspace manifest, calculate reverse-dependent impact from the exact PR diff, install local prerequisites in dependency order, and run the conservative affected Python test plan.
    commands:
      - python -m tools.openva.workspace validate
      - python -m tools.openva.workspace plan
    protects:
      - tools/openva/workspace.py
      - tools/openva/workspace.yaml
      - adapters/python/**
      - integrations/mcp/**
      - services/openva_match_service/**
      - integrations/google-sheets/**
'''
new_workspace = '''  workspace-plan:
    owner_loop: workspace_control_plane
    purpose: Validate the workspace manifest, calculate reverse-dependent impact from the exact PR diff, and publish whether the selected plan requires full regression coverage.
    commands:
      - python -m tools.openva.workspace validate
      - python -m tools.openva.workspace plan
    protects:
      - tools/openva/workspace.py
      - tools/openva/workspace.yaml
      - adapters/python/**
      - integrations/mcp/**
      - services/openva_match_service/**
      - integrations/google-sheets/**
  workspace-component-tests:
    owner_loop: workspace_control_plane
    purpose: Install the dependency chain and run only the selected Python tests when the workspace plan is component-scoped.
    commands:
      - python -m tools.openva.workspace validate
      - python -m tools.openva.workspace plan
      - subprocess.run([sys.executable, '-m', 'pytest', '-q', *plan['test_paths']], check=True)
    protects:
      - adapters/python/**
      - integrations/mcp/**
      - services/openva_match_service/**
      - integrations/google-sheets/**
  workspace-affected-tests:
    owner_loop: workspace_control_plane
    purpose: Preserve the required workspace status context and fail unless the delegated component tests or parallel full-regression shards succeed.
    commands:
      - echo "Full-suite plan validated by parallel regression shards."
      - echo "Targeted plan validated by component-scoped tests."
    protects:
      - tools/openva/workspace.py
      - tools/openva/workspace.yaml
      - adapters/python/**
      - integrations/mcp/**
      - services/openva_match_service/**
      - integrations/google-sheets/**
'''
if old_workspace not in text:
    raise SystemExit('existing workspace ownership block not found')
text = text.replace(old_workspace, new_workspace, 1)

old_workflow_command = (
    '      - pytest -q tests/test_ci_readiness.py tests/test_workflow_operating_model.py '
    'tests/test_workflow_retirement_evidence.py tests/test_future_operations_specs.py '
    'tests/test_workflow_contracts.py\n'
)
new_workflow_command = (
    '      - pytest -q tests/test_ci_readiness.py tests/test_workflow_operating_model.py '
    'tests/test_workflow_workspace_ci.py tests/test_workflow_retirement_evidence.py '
    'tests/test_future_operations_specs.py tests/test_workflow_contracts.py\n'
)
if old_workflow_command not in text:
    raise SystemExit('workflow operating-model ownership command not found')
text = text.replace(old_workflow_command, new_workflow_command, 1)

path.write_text(text, encoding='utf-8')
