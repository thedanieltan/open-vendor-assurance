import importlib.util
import json
from pathlib import Path

import yaml

_CONTRACT_PATH = Path(__file__).with_name("release_gates_contract.py")
_SPEC = importlib.util.spec_from_file_location("openva_release_gates_contract", _CONTRACT_PATH)
assert _SPEC and _SPEC.loader
_CONTRACT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONTRACT)

for _name, _value in vars(_CONTRACT).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


def test_contract_enforced_rule_no_direct_write_to_main():
    workflows = ROOT / ".github" / "workflows"

    for name in ("validate.yml", "release-image.yml"):
        workflow = yaml.safe_load((workflows / name).read_text(encoding="utf-8"))
        assert "write" not in json.dumps(workflow.get("permissions", {})), f"{name} must be read-only"

    pages = yaml.safe_load((workflows / "site-pages.yml").read_text(encoding="utf-8"))
    permissions = pages.get("permissions", {})
    assert permissions.get("contents") == "read"
    assert permissions.get("pages") == "write"
    assert "contents: write" not in (workflows / "site-pages.yml").read_text(encoding="utf-8")
    assert not (workflows / "release-candidate.yml").exists()
    assert not (workflows / "release-downloads.yml").exists()
