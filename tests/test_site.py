import importlib.util
from pathlib import Path

_CONTRACT_PATH = Path(__file__).resolve().parents[1] / ".github" / "test_support" / "site_contract.py"
_SPEC = importlib.util.spec_from_file_location("openva_site_contract", _CONTRACT_PATH)
assert _SPEC and _SPEC.loader
_CONTRACT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONTRACT)

for _name, _value in vars(_CONTRACT).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


def test_release_workflow_builds_compiled_site_distribution():
    assert not (WORKFLOWS / "release-downloads.yml").exists()
    pages = (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8")
    assert "python site/build.py --out site/dist" in pages
    assert "actions/deploy-pages@v4" in pages


def test_site_docs_cover_compiled_distribution_and_public_boundaries():
    readme_text = (SITE / "README.md").read_text(encoding="utf-8")
    launch_text = (ROOT / "docs" / "public-launch-checklist.md").read_text(encoding="utf-8")
    text = readme_text + "\n" + launch_text

    for phrase in [
        "static OpenVA contract and community-index browser",
        "Static site",
        "Resolver contract documentation",
        "Community index browser",
        "Local resolver / CLI / MCP entry point",
        "Result-pack preview",
        "Configurable source-pack builder",
        "Browser-local resolver",
        "Source pack preview",
        "Export Source Pack",
        "compiled static distribution",
        "vendor-search.min.json",
        "data/vendors/{vendor_id}.json",
        "browser memory only",
        "not written to `localStorage`, `sessionStorage`, a server, or a database",
        "no backend, database, account system, upload endpoint",
        "no live verification job",
        "no live discovery job",
        "no hosted resolver worker",
        "community index is hint-only",
        "consumer-side live verification",
        "openva_{source_type}_candidate_basis",
        "openva_{source_type}_verification_basis",
        "no server-side workspace persistence",
        "public metadata",
    ]:
        assert phrase in text

    for phrase in [
        "Hosted site uses compiled/sharded catalog outputs",
        "Vendor detail records are generated",
        "Browser-local matcher still processes private inventories in memory only",
        "compiled catalog distribution",
    ]:
        assert phrase not in readme_text
