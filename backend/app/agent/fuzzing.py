"""
Lightweight input fuzzing for the agent's "fill" action.

Pure stdlib (random) — no new dependencies, no extra Playwright/browser memory.
Some fraction of the time, the model's own chosen fill value is swapped for a
randomly selected edge-case payload, so form validation and error handling get
exercised too, not just whatever plausible-looking text the model types.

This is deliberately probabilistic rather than always-on: fuzzing every single
fill would mean the agent never successfully submits a valid-looking form, so
it would never explore whatever comes after a valid submission. FUZZ_PROBABILITY
balances "stress-test edge cases" against "still explore normal flows".
"""

import random

# ~40% of fill actions get fuzzed; the rest use the model's own chosen value.
FUZZ_PROBABILITY = 0.4

_ZERO_WIDTH_SPACE = "​"

FUZZ_PAYLOADS: dict[str, list[str]] = {
    "long_string": [
        "A" * 5000,
        ("word " * 800).strip(),
    ],
    "sql_injection": [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "1' UNION SELECT NULL--",
        "admin'--",
    ],
    "emoji": [
        "😀🔥💯🚀👾🎉🐍💀🤖🌀" * 3,
        "🙈🙉🙊🐵🙈",
    ],
    "whitespace": [
        "   ",
        "\n\n\n",
        "\t\t\t",
        _ZERO_WIDTH_SPACE * 3,  # often bypasses naive "required" checks
    ],
    "invalid_format": [
        "abcXYZ",             # letters where a numeric field is expected
        "not-an-email",
        "12/34/5678",          # malformed date
        "-999999999999",
        "999-999-9999x999",
    ],
}

_ALL_PAYLOADS: list[tuple[str, str]] = [
    (category, payload)
    for category, payloads in FUZZ_PAYLOADS.items()
    for payload in payloads
]


def should_fuzz() -> bool:
    """Decide whether this particular fill action should be fuzzed."""
    return random.random() < FUZZ_PROBABILITY


def get_fuzz_payload() -> tuple[str, str]:
    """Pick a random (category, payload) pair. Category is kept for logging/reproducibility."""
    return random.choice(_ALL_PAYLOADS)
