"""
Unit tests for the input-fuzzing module (agent/fuzzing.py).
"""

from app.agent import fuzzing


def test_should_fuzz_respects_probability():
    """Over many samples, the fuzz rate should land near FUZZ_PROBABILITY."""
    samples = [fuzzing.should_fuzz() for _ in range(2000)]
    rate = sum(samples) / len(samples)
    assert abs(rate - fuzzing.FUZZ_PROBABILITY) < 0.07, (
        f"Observed fuzz rate {rate:.3f} too far from configured {fuzzing.FUZZ_PROBABILITY}"
    )


def test_expected_categories_present():
    expected = {"long_string", "sql_injection", "emoji", "whitespace", "invalid_format"}
    assert expected <= set(fuzzing.FUZZ_PAYLOADS.keys())


def test_all_payloads_are_nonempty_strings():
    for category, payloads in fuzzing.FUZZ_PAYLOADS.items():
        assert payloads, f"category {category!r} has no payloads"
        for payload in payloads:
            assert isinstance(payload, str)
            assert len(payload) > 0


def test_long_string_payload_is_actually_long():
    long_payloads = fuzzing.FUZZ_PAYLOADS["long_string"]
    assert any(len(p) >= 1000 for p in long_payloads)


def test_get_fuzz_payload_returns_known_category_and_payload():
    for _ in range(50):
        category, payload = fuzzing.get_fuzz_payload()
        assert category in fuzzing.FUZZ_PAYLOADS
        assert payload in fuzzing.FUZZ_PAYLOADS[category]


def test_get_fuzz_payload_covers_multiple_categories_over_many_calls():
    seen_categories = {fuzzing.get_fuzz_payload()[0] for _ in range(500)}
    # With 500 draws across 5 categories, we should see essentially all of them.
    assert len(seen_categories) == len(fuzzing.FUZZ_PAYLOADS)
