from tools.openva.advisory_wording import prohibited_terms_in_text


def test_prohibited_term_matches_standalone_word():
    assert prohibited_terms_in_text("The page says this is safe for regulated workloads.", ["safe"]) == ["safe"]


def test_prohibited_term_does_not_match_inside_snake_case_identifier():
    # render_transport values like "playwright_intercepted_safe_fetch" are internal
    # fetch-mechanism metadata, not an editorial claim about the vendor's product.
    assert prohibited_terms_in_text("render_transport: playwright_intercepted_safe_fetch", ["safe"]) == []


def test_prohibited_term_does_not_match_inside_hyphenated_identifier():
    assert prohibited_terms_in_text("verification-safe-mode enabled", ["safe"]) == []
