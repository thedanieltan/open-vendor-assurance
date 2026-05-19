from tools.openva.indexes import build_contracting_entity_resolution, build_search_index, build_source_coverage, vendor_manifest


def record_sets():
    return {
        "vendor": [
            {
                "vendor_id": "example",
                "display_name": "Example",
                "legal_name": "Example Inc.",
                "official_domains": ["example.test"],
                "headquarters_country": "US",
                "status": "active",
            }
        ],
        "source": [{"vendor_id": "example", "source_id": "example-dpa", "source_type": "dpa"}],
        "artifact": [],
        "observation": [],
        "change": [],
        "legal_entity": [
            {
                "entity_id": "example-us",
                "vendor_id": "example",
                "catalog_status": "canonical",
                "contracting_jurisdictions": [
                    {
                        "jurisdiction": "US",
                        "role": "primary_contracting_entity",
                        "confidence": "high",
                        "source_id": "example-dpa",
                        "summary": "Public source identifies the US contracting entity.",
                    }
                ],
            },
            {"entity_id": "example-stub", "vendor_id": "example", "catalog_status": "stub"},
        ],
        "entity_mention": [{"mention_id": "example-mention", "vendor_id": "example"}],
        "candidate_source": [
            {
                "vendor_id": "example",
                "candidate_source_id": "example-security-candidate",
                "source_type_candidate": "security_page",
            }
        ],
        "unavailable_source": [
            {
                "vendor_id": "example",
                "unavailable_source_id": "example-subprocessors-list",
                "source_type": "subprocessors_list",
            }
        ],
    }


def test_vendor_manifest_exposes_canonical_candidate_and_unavailable_records():
    manifest = vendor_manifest(
        record_sets()["vendor"][0],
        record_sets()["source"],
        [],
        [],
        [],
        record_sets()["legal_entity"],
        record_sets()["entity_mention"],
        record_sets()["candidate_source"],
        record_sets()["unavailable_source"],
    )

    assert manifest["summary"]["canonical_source_count"] == 1
    assert manifest["summary"]["candidate_source_count"] == 1
    assert manifest["summary"]["unavailable_source_count"] == 1
    assert manifest["summary"]["source_types"] == ["dpa"]
    assert manifest["summary"]["candidate_source_types"] == ["security_page"]
    assert manifest["summary"]["unavailable_source_types"] == ["subprocessors_list"]
    assert manifest["guarantees"]["non_advisory"] is True
    assert manifest["guarantees"]["raw_documents_mirrored_by_default"] is False


def test_vendor_search_index_points_to_manifest_and_source_statuses():
    search = build_search_index(record_sets())
    item = search["items"][0]

    assert search["count"] == 1
    assert item["vendor_id"] == "example"
    assert item["manifest_path"] == "dist/vendors/example.json"
    assert item["source_types"] == ["dpa"]
    assert item["candidate_source_types"] == ["security_page"]
    assert item["unavailable_source_types"] == ["subprocessors_list"]


def test_source_coverage_counts_canonical_candidate_and_unavailable_types():
    coverage = build_source_coverage(record_sets())

    assert coverage["source_type_counts"] == {"dpa": 1}
    assert coverage["candidate_source_type_counts"] == {"security_page": 1}
    assert coverage["unavailable_source_type_counts"] == {"subprocessors_list": 1}


def test_vendor_manifest_semantics_are_adapter_safe():
    manifest = vendor_manifest(
        record_sets()["vendor"][0],
        record_sets()["source"],
        [],
        [{"result": "bot_protected", "http_status": 403}],
        [],
        [],
        [],
        record_sets()["candidate_source"],
        record_sets()["unavailable_source"],
    )

    assert manifest["canonical_sources"][0]["source_type"] == "dpa"
    assert manifest["candidate_sources"][0]["source_type_candidate"] == "security_page"
    assert manifest["unavailable_sources"][0]["source_type"] == "subprocessors_list"
    assert manifest["observations"][0]["result"] == "bot_protected"
    assert manifest["guarantees"]["non_advisory"] is True


def test_contracting_entity_resolution_includes_canonical_entities_only():
    resolution = build_contracting_entity_resolution(record_sets())

    assert resolution["count"] == 1
    item = resolution["items"][0]
    assert item["vendor_id"] == "example"
    assert item["jurisdiction"] == "US"
    assert item["resolution_status"] == "resolved"
    assert item["resolved_entity_id"] == "example-us"
    assert item["candidate_entity_ids"] == ["example-us"]
