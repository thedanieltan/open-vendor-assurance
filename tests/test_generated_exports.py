import json
from pathlib import Path

from tools.openva.agent_export import build_agent_exports, payload_digest
from tools.openva.pack import canonical_json, sha256_bytes

from tests.test_agent_export import (
    COMMIT_SHA,
    GENERATED_AT,
    freshness_artifact,
    make_repo,
    run_artifact,
    write_ledger_event,
)


def build_into(tmp_path: Path, out_name: str) -> Path:
    out = tmp_path / out_name
    build_agent_exports(
        root=tmp_path,
        out_dir=out,
        commit_sha=COMMIT_SHA,
        generated_at=GENERATED_AT,
        ledger_dir=tmp_path / "maintenance" / "source-observations" / "events",
        latest_observations=run_artifact(),
        freshness_report=freshness_artifact(),
    )
    return out


def tree_bytes(out: Path) -> dict[str, bytes]:
    return {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in sorted(out.rglob("*.json"))
    }


def test_identical_pinned_inputs_produce_byte_identical_trees(tmp_path):
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")

    first = tree_bytes(build_into(tmp_path, "out-a"))
    second = tree_bytes(build_into(tmp_path, "out-b"))

    assert first.keys() == second.keys()
    assert first == second


def test_digest_is_verifiable_by_recomputation(tmp_path):
    make_repo(tmp_path)
    out = build_into(tmp_path, "out")

    for path in sorted(out.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        material = {key: value for key, value in document.items() if key != "snapshot"}
        recomputed = sha256_bytes(canonical_json(material))
        assert document["snapshot"]["digest"] == recomputed, path.name
        assert document["snapshot"]["digest"] == payload_digest(document), path.name


def test_root_index_digests_match_per_file_digests_and_exclude_root(tmp_path):
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    out = build_into(tmp_path, "out")
    index = json.loads((out / "openva-agent-index.json").read_text(encoding="utf-8"))

    # Non-recursive rule: the exports map excludes the root index itself.
    listed_paths = [pointer["path"] for pointer in index["exports"].values()]
    listed_paths += [entry["path"] for entry in index["vendor_exports"]]
    assert "openva-agent-index.json" not in listed_paths

    for pointer in index["exports"].values():
        document = json.loads((out / pointer["path"]).read_text(encoding="utf-8"))
        assert document["snapshot"]["digest"] == pointer["digest"], pointer["path"]
    for entry in index["vendor_exports"]:
        document = json.loads((out / entry["path"]).read_text(encoding="utf-8"))
        assert document["snapshot"]["digest"] == entry["digest"], entry["path"]


def test_digest_changes_when_a_source_record_changes(tmp_path):
    make_repo(tmp_path)
    before = json.loads(
        (build_into(tmp_path, "out-before") / "vendors/example-vendor.json").read_text(encoding="utf-8")
    )

    source_path = tmp_path / "data/vendors/example-vendor/sources/example-vendor-privacy.yaml"
    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace(
            "https://vendor.example/privacy", "https://vendor.example/legal/privacy"
        ),
        encoding="utf-8",
    )
    after = json.loads(
        (build_into(tmp_path, "out-after") / "vendors/example-vendor.json").read_text(encoding="utf-8")
    )

    assert before["snapshot"]["digest"] != after["snapshot"]["digest"]


def test_ordering_is_deterministic_and_sorted(tmp_path):
    make_repo(tmp_path)
    other = tmp_path / "data" / "vendors" / "a-first-vendor"
    (other / "sources").mkdir(parents=True)
    (other / "vendor.yaml").write_text(
        "vendor_id: a-first-vendor\ndisplay_name: A First Vendor\nofficial_domains:\n  - first.example\n",
        encoding="utf-8",
    )
    out = build_into(tmp_path, "out")

    vendors = json.loads((out / "vendors/index.json").read_text(encoding="utf-8"))["vendors"]
    assert [row["vendor_id"] for row in vendors] == ["a-first-vendor", "example-vendor"]

    sources = json.loads((out / "sources/index.json").read_text(encoding="utf-8"))["sources"]
    assert [row["source_id"] for row in sources] == sorted(row["source_id"] for row in sources)
