from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = "thedanieltan/open-vendor-assurance"
PR_NUMBER = "821"
CANDIDATE = Path(".github/workflows/candidate-promotion-pr.yml")
BRIDGE = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
MODULE = Path("tools/openva/discovery_promotion_bridge.py")
TEST = Path("tests/test_discovery_promotion_bridge.py")
FOCUSED = Path("tests/test_catalog_growth_artifact_bound_promotion.py")
TEMP_PATHS = [
    ".github/workflows/zz-temp-artifact-bound-patch.yml",
    ".github/workflows/zz-temp-pr-runner.yml",
    ".github/workflows/zz-temp-object-trigger.yml",
    "tools/openva/zz_temp_artifact_bound_object_builder.py",
]


def run(*args: str, input_text: str | None = None) -> str:
    proc = subprocess.run(
        args,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    return proc.stdout.strip()


def apply_patch_program() -> None:
    source = Path(".github/workflows/zz-temp-artifact-bound-patch.yml").read_text(encoding="utf-8")
    start_marker = "          python - <<'PY'\n"
    end_marker = "\n          PY\n      - name: Commit patched branch"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    lines = source[start:end].splitlines()
    program = "\n".join(line[10:] if line.startswith("          ") else line for line in lines) + "\n"
    namespace: dict[str, object] = {"__name__": "__main__"}
    exec(compile(program, "artifact-bound-patch", "exec"), namespace, namespace)


def repair_generated_files() -> None:
    text = CANDIDATE.read_text(encoding="utf-8")
    old_event = '[ "$DISCOVERY_EVENT" = "schedule" ] || { echo "::error::artifact-bound automatic promotion requires a scheduled discovery run"; exit 1; }'
    new_event = '''case "$DISCOVERY_EVENT" in
            schedule|workflow_dispatch) ;;
            *) echo "::error::artifact-bound promotion source event is not authorized: $DISCOVERY_EVENT"; exit 1 ;;
          esac'''
    if text.count(old_event) != 1:
        raise RuntimeError("expected exactly one schedule-only artifact event gate")
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
        raise RuntimeError("expected exactly one malformed PR provenance block")
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
        raise RuntimeError("expected exactly one malformed artifact upload block")
    CANDIDATE.write_text(text.replace(old_upload, new_upload), encoding="utf-8")

    body = FOCUSED.read_text(encoding="utf-8")
    old = '''    assert 'DISCOVERY_EVENT" = "schedule"' in step
'''
    new = '''    assert 'schedule|workflow_dispatch' in step
    assert 'artifact-bound promotion source event is not authorized' in step
'''
    if body.count(old) != 1:
        raise RuntimeError("expected exactly one focused schedule-only assertion")
    FOCUSED.write_text(body.replace(old, new), encoding="utf-8")


def gh_json(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    return json.loads(run("gh", "api", "--method", "POST", endpoint, "--input", "-", input_text=json.dumps(payload)))


def blob(path: Path) -> str:
    response = gh_json(f"repos/{REPO}/git/blobs", {"content": path.read_text(encoding="utf-8"), "encoding": "utf-8"})
    return str(response["sha"])


def main() -> None:
    apply_patch_program()
    repair_generated_files()
    run("ruby", "-e", 'require "yaml"; YAML.load_file(".github/workflows/candidate-promotion-pr.yml"); YAML.load_file(".github/workflows/catalog-growth-promotion-bridge.yml")')
    run("python", "-m", "py_compile", str(MODULE), str(TEST), str(FOCUSED))
    run("git", "diff", "--check")

    base_head = run("git", "rev-parse", "HEAD")
    base_tree = run("git", "rev-parse", "HEAD^{tree}")
    entries = [
        {"path": str(CANDIDATE), "mode": "100644", "type": "blob", "sha": blob(CANDIDATE)},
        {"path": str(BRIDGE), "mode": "100644", "type": "blob", "sha": blob(BRIDGE)},
        {"path": str(MODULE), "mode": "100644", "type": "blob", "sha": blob(MODULE)},
        {"path": str(TEST), "mode": "100644", "type": "blob", "sha": blob(TEST)},
        {"path": str(FOCUSED), "mode": "100644", "type": "blob", "sha": blob(FOCUSED)},
    ]
    entries.extend({"path": path, "mode": "100644", "type": "blob", "sha": None} for path in TEMP_PATHS)
    tree = gh_json(f"repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    commit = gh_json(
        f"repos/{REPO}/git/commits",
        {"message": "Bind catalog growth promotion to discovery artifact", "tree": tree["sha"], "parents": [base_head]},
    )
    commit_sha = str(commit["sha"])
    message = "\n".join(
        [
            "Artifact-bound promotion production commit object generated.",
            "",
            f"ARTIFACT_BOUND_OBJECT_COMMIT={commit_sha}",
            f"ARTIFACT_BOUND_OBJECT_PARENT={base_head}",
            f"ARTIFACT_BOUND_OBJECT_TREE={tree['sha']}",
            "",
            "The branch ref was intentionally not moved by the workflow. The connected GitHub API must verify the parent and advance the draft PR branch to this commit.",
        ]
    )
    run("gh", "pr", "comment", PR_NUMBER, "--repo", REPO, "--body", message)
    print(message)


if __name__ == "__main__":
    main()
