from pathlib import Path


def test_adapter_contract_documents_interpretation_boundary():
    text = Path("docs/adapter-contract.md").read_text(encoding="utf-8")

    for phrase in [
        "candidate_sources` are non-canonical review candidates",
        "unavailable_sources` are reviewed absence or omission records",
        "observations` and source verification reports are fetch-time facts",
        "They are not source-removal decisions",
        "OpenVA exports public metadata only",
    ]:
        assert phrase in text


def test_adapter_contract_documents_first_class_outputs():
    text = Path("docs/adapter-contract.md").read_text(encoding="utf-8")

    for path in [
        "openva-pack.json",
        "indexes/candidate-sources.json",
        "indexes/unavailable-sources.json",
        "indexes/vendor-search.json",
        "indexes/source-coverage.json",
        "dist/vendors/{vendor_id}.json",
    ]:
        assert path in text


def test_adapter_output_contract_documents_normalized_annotations():
    text = Path("docs/adapter-output-contract.md").read_text(encoding="utf-8")

    for phrase in [
        "record_class",
        "canonical",
        "advisory_boundary",
        "non_advisory",
        "multi-source downstream systems",
        "`v0.2.0` or `openva-export-pack.v2`",
    ]:
        assert phrase in text
