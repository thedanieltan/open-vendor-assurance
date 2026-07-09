from tools.openva.entity_evidence_quorum import (
    FAIL_STATUS,
    PASS_STATUS,
    REASON_CONFLICTING_REGISTRATION_NUMBER,
    REASON_CONTRACTING_SCOPE_UNSUPPORTED,
    REASON_CORROBORATING_SOURCE_MISSING,
    REASON_ENTITY_SCOPE_AMBIGUOUS,
    REASON_OFFICIAL_SOURCE_MISSING,
    REASON_REGISTRATION_NUMBER_MISSING,
    REASON_VERIFICATION_SOURCE_MISSING,
    evaluate_entity_evidence_quorum,
)


def _legal_entity(**overrides):
    entity = {
        "entity_id": "example-payments-ltd",
        "vendor_id": "examplepay",
        "legal_name": "Example Payments Ltd",
        "jurisdiction": "GB",
        "registration_number": "12345678",
        "verification_source_ids": [
            "example-payments-registry",
            "example-payments-terms",
        ],
    }
    entity.update(overrides)
    return entity


def _registry_source(**overrides):
    source = {
        "source_id": "example-payments-registry",
        "vendor_id": "examplepay",
        "entity_id": "example-payments-ltd",
        "source_type": "other_public_source",
        "source_authority_class": "public_registry",
        "registration_number": "12345678",
    }
    source.update(overrides)
    return source


def _corroborating_source(**overrides):
    source = {
        "source_id": "example-payments-terms",
        "vendor_id": "examplepay",
        "entity_id": "example-payments-ltd",
        "source_type": "terms",
        "source_authority_class": "vendor_published",
    }
    source.update(overrides)
    return source


def test_passes_with_official_registry_and_distinct_entity_corroboration():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(),
        [_registry_source(), _corroborating_source()],
    )

    assert decision.status == PASS_STATUS
    assert decision.passed is True
    assert decision.official_source_ids == ("example-payments-registry",)
    assert decision.corroborating_source_ids == ("example-payments-terms",)
    assert decision.reason_codes == ()


def test_fails_when_registration_number_is_missing():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(registration_number=None),
        [_registry_source(), _corroborating_source()],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_REGISTRATION_NUMBER_MISSING in decision.reason_codes


def test_fails_with_registry_source_only():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(verification_source_ids=["example-payments-registry"]),
        [_registry_source()],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_CORROBORATING_SOURCE_MISSING in decision.reason_codes


def test_fails_when_official_source_is_brand_level_not_entity_scoped():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(),
        [
            _registry_source(entity_id=None),
            _corroborating_source(),
        ],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_OFFICIAL_SOURCE_MISSING in decision.reason_codes


def test_fails_when_brand_only_public_source_is_used_as_corroboration():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(),
        [
            _registry_source(),
            _corroborating_source(entity_id=None),
        ],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_CORROBORATING_SOURCE_MISSING in decision.reason_codes


def test_accepts_corrobating_source_that_repeats_registration_number():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(),
        [
            _registry_source(),
            _corroborating_source(entity_id=None, registration_number="12345678"),
        ],
    )

    assert decision.status == PASS_STATUS
    assert decision.corroborating_source_ids == ("example-payments-terms",)


def test_fails_on_conflicting_registration_number_evidence():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(),
        [
            _registry_source(),
            _corroborating_source(registration_number="99999999"),
        ],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_CONFLICTING_REGISTRATION_NUMBER in decision.reason_codes


def test_fails_when_global_brand_scope_is_ambiguous():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(multiple_plausible_entities=True),
        [_registry_source(), _corroborating_source()],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_ENTITY_SCOPE_AMBIGUOUS in decision.reason_codes


def test_fails_when_contracting_scope_lacks_source_support():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(
            contracting_jurisdictions=[
                {"jurisdiction": "GB", "role": "contracting_party"},
            ],
        ),
        [_registry_source(), _corroborating_source()],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_CONTRACTING_SCOPE_UNSUPPORTED in decision.reason_codes


def test_passes_contracting_scope_when_source_backed():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(
            contracting_jurisdictions=[
                {
                    "jurisdiction": "GB",
                    "role": "contracting_party",
                    "source_id": "example-payments-terms",
                },
            ],
        ),
        [_registry_source(), _corroborating_source()],
    )

    assert decision.status == PASS_STATUS


def test_fails_when_declared_verification_source_is_missing():
    decision = evaluate_entity_evidence_quorum(
        _legal_entity(verification_source_ids=["example-payments-registry", "missing-source"]),
        [_registry_source()],
    )

    assert decision.status == FAIL_STATUS
    assert REASON_VERIFICATION_SOURCE_MISSING in decision.reason_codes
