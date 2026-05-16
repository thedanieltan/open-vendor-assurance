from pathlib import Path


DOC = Path("docs/maintenance/reviewed-candidate-promotion.md")


def test_reviewed_candidate_promotion_doc_names_guarded_action():
    text = DOC.read_text(encoding="utf-8")

    assert "promote_candidate_source_for_review" in text
    assert "Candidate sources are discovery outputs" in text
    assert "not canonical catalog sources" in text
    assert "requires_human_review: true" in text
    assert "writes_canonical_sources: false" in text
    assert "non_advisory: true" in text
    assert "no candidate auto-promotion" in text
    assert "no raw vendor document mirroring" in text
