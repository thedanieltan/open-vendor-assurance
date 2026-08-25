from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = "thedanieltan/open-vendor-assurance"
PR = "821"
BASE_SHA = "9f797629f145b118874ea899a32f23481d3e3240"
PATCH_SOURCE_SHA = "f2d04de162abc2dcdbafe3594badbc9a68cf0908"
COVERAGE_BASE_BLOB = "9b5f25c18521681569d2cc589e5de5fb551f7d6a"
CANDIDATE = Path(".github/workflows/candidate-promotion-pr.yml")
BRIDGE = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
MODULE = Path("tools/openva/discovery_promotion_bridge.py")
TEST = Path("tests/test_discovery_promotion_bridge.py")
FOCUSED = Path("tests/test_catalog_growth_artifact_bound_promotion.py")
SELF = "tools/openva/zz_temp_rebuild_artifact_bound.py"


def run(*args: str, input_text: str | None = None) -> str:
    proc = subprocess.run(args, input=input_text, text=True, check=True, stdout=subprocess.PIPE)
    return proc.stdout.strip()


def apply_original_patch() -> None:
    run(
        "git", "checkout", BASE_SHA, "--",
        str(CANDIDATE), str(BRIDGE), str(MODULE), str(TEST),
    )
    FOCUSED.unlink(missing_ok=True)
    source = run("git", "show", f"{PATCH_SOURCE_SHA}:.github/workflows/zz-temp-artifact-bound-patch.yml")
    marker_start = "          python - <<'PY'\n"
    marker_end = "\n          PY\n      - name: Commit patched branch"
    start = source.index(marker_start) + len(marker_start)
    end = source.index(marker_end, start)
    lines = source[start:end].splitlines()
    program = "\n".join(line[10:] if line.startswith("          ") else line for line in lines) + "\n"
    namespace: dict[str, object] = {"__name__": "__main__"}
    exec(compile(program, "artifact-bound-production-patch", "exec"), namespace, namespace)


def repair_generated_files() -> None:
    text = CANDIDATE.read_text(encoding="utf-8")
    old_event = '[ "$DISCOVERY_EVENT" = "schedule" ] || { echo "::error::artifact-bound automatic promotion requires a scheduled discovery run"; exit 1; }'
    new_event = '''case "$DISCOVERY_EVENT" in
            schedule|workflow_dispatch) ;;
            *) echo "::error::artifact-bound promotion source event is not authorized: $DISCOVERY_EVENT"; exit 1 ;;
          esac'''
    if text.count(old_event) != 1:
        raise RuntimeError("expected one schedule-only artifact event gate")
    text = text.replace(old_event, new_event)

    step_start = text.index("      - name: Load artifact-bound strict-growth evidence\n")
    step_end = text.index("      - name: Regenerate strict-growth promotion plan\n", step_start)
    block = text[step_start:step_end].splitlines()
    run_idx = block.index("        run: |")
    env_idx = block.index("        env:")
    if run_idx != env_idx + 2 or not block[env_idx + 1].startswith("GH_TOKEN:"):
        raise RuntimeError("unexpected generated artifact step structure")
    block[env_idx + 1] = "          " + block[env_idx + 1]
    for idx in range(run_idx + 1, len(block)):
        if block[idx]:
            block[idx] = "          " + block[idx]
    text = text[:step_start] + "\n".join(block) + "\n" + text[step_end:]

    old_body = '''          if os.environ.get('SOURCE_DISCOVERY_RUN_ID'):
    insert_at = lines.index('## Counts') - 1
    lines[insert_at:insert_at] = [
        f"- Source discovery run: `{os.environ['SOURCE_DISCOVERY_RUN_ID']}`",
        f"- Source discovery artifact: `{os.environ['SOURCE_DISCOVERY_ARTIFACT_ID']}`",
        f"- Source discovery plan SHA-256: `{os.environ['SOURCE_DISCOVERY_PLAN_DIGEST']}`",
    ]
'''
    new_body = '''          if os.environ.get('SOURCE_DISCOVERY_RUN_ID'):
              insert_at = lines.index('## Counts') - 1
              lines[insert_at:insert_at] = [
                  f"- Source discovery run: `{os.environ['SOURCE_DISCOVERY_RUN_ID']}`",
                  f"- Source discovery artifact: `{os.environ['SOURCE_DISCOVERY_ARTIFACT_ID']}`",
                  f"- Source discovery plan SHA-256: `{os.environ['SOURCE_DISCOVERY_PLAN_DIGEST']}`",
              ]
'''
    if text.count(old_body) != 1:
        raise RuntimeError("expected one malformed PR provenance block")
    text = text.replace(old_body, new_body)

    old_upload = '''        with:
name: openva-candidate-promotion-pr-artifact-bound-source
path: |
  strict-growth-source-plan.json
  catalog-growth-source-eligibility-report.json
  vendor-candidate-discovery-report.json
  vendor-candidate-source-discovery-report.json
  catalog-growth-backlog-report.json
  strict-growth-shortlist.json
if-no-files-found: warn
      - name: Build catalog promotion failure routing input
'''
    new_upload = '''        with:
          name: openva-candidate-promotion-pr-artifact-bound-source
          path: |
            strict-growth-source-plan.json
            catalog-growth-source-eligibility-report.json
            vendor-candidate-discovery-report.json
            vendor-candidate-source-discovery-report.json
            catalog-growth-backlog-report.json
            strict-growth-shortlist.json
          if-no-files-found: warn
      - name: Build catalog promotion failure routing input
'''
    if text.count(old_upload) != 1:
        raise RuntimeError("expected one malformed artifact upload block")
    CANDIDATE.write_text(text.replace(old_upload, new_upload), encoding="utf-8")

    body = FOCUSED.read_text(encoding="utf-8")
    old = '''    assert 'DISCOVERY_EVENT" = "schedule"' in step
'''
    new = '''    assert 'schedule|workflow_dispatch' in step
    assert 'artifact-bound promotion source event is not authorized' in step
'''
    if body.count(old) != 1:
        raise RuntimeError("expected one focused schedule-only assertion")
    FOCUSED.write_text(body.replace(old, new), encoding="utf-8")


def validate() -> None:
    run("ruby", "-e", 'require "yaml"; YAML.load_file(".github/workflows/candidate-promotion-pr.yml"); YAML.load_file(".github/workflows/catalog-growth-promotion-bridge.yml")')
    run("python", "-m", "py_compile", str(MODULE), str(TEST), str(FOCUSED))
    run("git", "diff", "--check")
    numstat = run("git", "diff", "--numstat", BASE_SHA, "--", str(CANDIDATE), str(BRIDGE))
    print(numstat)
    for line in numstat.splitlines():
        add, delete, path = line.split("\t", 2)
        if int(delete) >= 100:
            raise RuntimeError(f"deletion guard tripped for {path}: {delete}")


def gh_json(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    return json.loads(run("gh", "api", "--method", "POST", endpoint, "--input", "-", input_text=json.dumps(payload)))


def make_blob(path: Path) -> str:
    result = gh_json(f"repos/{REPO}/git/blobs", {"content": path.read_text(encoding="utf-8"), "encoding": "utf-8"})
    return str(result["sha"])


def build_commit() -> str:
    head = run("git", "rev-parse", "HEAD")
    base_tree = run("git", "rev-parse", "HEAD^{tree}")
    entries: list[dict[str, object]] = [
        {"path": str(CANDIDATE), "mode": "100644", "type": "blob", "sha": make_blob(CANDIDATE)},
        {"path": str(BRIDGE), "mode": "100644", "type": "blob", "sha": make_blob(BRIDGE)},
        {"path": str(MODULE), "mode": "100644", "type": "blob", "sha": make_blob(MODULE)},
        {"path": str(TEST), "mode": "100644", "type": "blob", "sha": make_blob(TEST)},
        {"path": str(FOCUSED), "mode": "100644", "type": "blob", "sha": make_blob(FOCUSED)},
        {"path": ".github/workflows/coverage-audit.yml", "mode": "100644", "type": "blob", "sha": COVERAGE_BASE_BLOB},
        {"path": SELF, "mode": "100644", "type": "blob", "sha": None},
    ]
    tree = gh_json(f"repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    commit = gh_json(
        f"repos/{REPO}/git/commits",
        {"message": "Bind catalog growth promotion to discovery artifact", "tree": tree["sha"], "parents": [head]},
    )
    return str(commit["sha"])


def main() -> None:
    apply_original_patch()
    repair_generated_files()
    validate()
    commit = build_commit()
    print(f"CLEAN_ARTIFACT_BOUND_OBJECT_COMMIT={commit}")
    run(
        "gh", "pr", "comment", PR, "--repo", REPO, "--body",
        f"CLEAN_ARTIFACT_BOUND_OBJECT_COMMIT={commit}\nCLEAN_ARTIFACT_BOUND_OBJECT_PARENT={run('git','rev-parse','HEAD')}",
    )


if __name__ == "__main__":
    main()
