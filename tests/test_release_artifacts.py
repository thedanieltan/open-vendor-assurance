from pathlib import Path

from tools.openva import release_artifacts
from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, SCHEMA_VERSION


def test_artifact_paths_include_release_facing_files():
    paths = {path.relative_to(release_artifacts.ROOT).as_posix() for path in release_artifacts.artifact_paths()}

    assert "openva-pack.json" in paths
    assert "indexes/vendors.json" in paths
    assert "indexes/sources.json" in paths
    assert "indexes/artifacts.json" in paths
    assert "indexes/summary.json" in paths
    assert "indexes/vendor-search.json" in paths
    assert "indexes/vendor-match-index.json" in paths
    assert "indexes/source-coverage.json" in paths
    assert any(path.startswith("dist/vendors/") for path in paths)
    assert "public/assurance-intelligence.json" in release_artifacts.ARTIFACT_PATTERNS
    assert "schemas/openva/openva-pack.schema.json" in paths
    assert "fixtures/packs/minimal-valid/openva-pack.json" in paths


def test_build_manifest_has_expected_release_contract_fields():
    manifest = release_artifacts.build_manifest()

    assert manifest["schema_version"] == release_artifacts.MANIFEST_SCHEMA_VERSION
    assert manifest["profileId"] == EXPORT_PROFILE_ID
    assert manifest["schemaVersion"] == EXPORT_SCHEMA_VERSION
    assert manifest["record_schema_version"] == SCHEMA_VERSION
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    assert manifest["artifact_count"] > 0


def test_build_manifest_artifacts_have_sha256_and_size():
    manifest = release_artifacts.build_manifest()

    for artifact in manifest["artifacts"]:
        assert set(artifact) == {"path", "sha256", "size_bytes"}
        assert artifact["sha256"].startswith("sha256:")
        assert len(artifact["sha256"]) == len("sha256:") + 64
        assert artifact["size_bytes"] > 0
        assert not Path(artifact["path"]).is_absolute()
        assert ".." not in Path(artifact["path"]).parts


def test_release_artifacts_manifest_is_deterministic():
    assert release_artifacts.build_manifest() == release_artifacts.build_manifest()


def test_release_artifacts_excludes_manifest_itself(monkeypatch, tmp_path):
    fake_root = tmp_path
    (fake_root / "indexes").mkdir()
    (fake_root / "indexes/vendors.json").write_text("{}\n", encoding="utf-8")
    (fake_root / "release-artifacts.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(release_artifacts, "ROOT", fake_root)
    monkeypatch.setattr(release_artifacts, "MANIFEST_PATH", fake_root / "release-artifacts.json")
    monkeypatch.setattr(release_artifacts, "ARTIFACT_PATTERNS", ["indexes/*.json", "release-artifacts.json"])
    monkeypatch.setattr(release_artifacts, "REQUIRED_ARTIFACTS", [])

    paths = {path.relative_to(fake_root).as_posix() for path in release_artifacts.artifact_paths()}

    assert paths == {"indexes/vendors.json"}


def test_check_manifest_current_reports_missing_when_not_committed(monkeypatch, tmp_path):
    fake_root = tmp_path
    monkeypatch.setattr(release_artifacts, "ROOT", fake_root)
    monkeypatch.setattr(release_artifacts, "MANIFEST_PATH", fake_root / "release-artifacts.json")
    monkeypatch.setattr(release_artifacts, "ARTIFACT_PATTERNS", [])
    monkeypatch.setattr(release_artifacts, "REQUIRED_ARTIFACTS", [])

    assert release_artifacts.check_manifest_current() == [
        "release-artifacts.json is missing; run python -m tools.openva.release_artifacts build"
    ]


def test_check_manifest_current_requires_assurance_intelligence_artifact(monkeypatch, tmp_path):
    fake_root = tmp_path
    monkeypatch.setattr(release_artifacts, "ROOT", fake_root)
    monkeypatch.setattr(release_artifacts, "MANIFEST_PATH", fake_root / "release-artifacts.json")
    monkeypatch.setattr(release_artifacts, "ARTIFACT_PATTERNS", ["public/assurance-intelligence.json"])
    monkeypatch.setattr(release_artifacts, "REQUIRED_ARTIFACTS", ["public/assurance-intelligence.json"])

    assert release_artifacts.check_manifest_current() == [
        "required release artifact is missing: public/assurance-intelligence.json; "
        "run python -m tools.openva.assurance_intelligence_publication build"
    ]


def test_build_manifest_includes_assurance_intelligence_when_present(monkeypatch, tmp_path):
    fake_root = tmp_path
    artifact = fake_root / "public" / "assurance-intelligence.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(release_artifacts, "ROOT", fake_root)
    monkeypatch.setattr(release_artifacts, "MANIFEST_PATH", fake_root / "release-artifacts.json")
    monkeypatch.setattr(release_artifacts, "ARTIFACT_PATTERNS", ["public/assurance-intelligence.json"])
    monkeypatch.setattr(release_artifacts, "REQUIRED_ARTIFACTS", ["public/assurance-intelligence.json"])

    manifest = release_artifacts.build_manifest()

    assert [item["path"] for item in manifest["artifacts"]] == ["public/assurance-intelligence.json"]
