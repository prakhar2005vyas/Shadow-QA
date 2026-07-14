"""
Mock VLM — returns deterministic, scripted AgentStep responses.

Used when MOCK_VLM=true (the default). Zero GPU calls, zero cost.
The script is keyed on step_index so the full agent loop exercises
the fixture-app bugs predictably and the integration test can assert
on specific findings.

Every response is a valid AgentStep — the same schema the real vLLM
returns — so the loop code doesn't need to know it's talking to a mock.
"""

from .schemas import AgentStep, NextAction, Anomaly

# ---------------------------------------------------------------------------
# Scripted sequence — one entry per step_index.
# Surfaces 7 of the 9 seeded bugs in fixture-app/BUGS.md — B01, B03, B04, B05,
# B06, B07, B08 — across four categories. B02 (contact-form 404) and B09
# (disabled export button) are deliberately left for the real VLM to find, so
# mock and real runs differ.
# ---------------------------------------------------------------------------
_SCRIPT: list[dict] = [
    # step 0 — land on page, immediately flag layout overflow (bug #3)
    {
        "observation": (
            "Page loaded. The hero section visibly extends beyond the viewport "
            "width at the current 1280px viewport, creating an unwanted horizontal "
            "scrollbar. The CSS sets width:120vw with no overflow:hidden on the parent."
        ),
        "anomaly": {
            "description": (
                "Hero div overflows viewport horizontally (CSS: width:120vw, no overflow:hidden "
                "on parent). At mobile widths (≤480px) this breaks the entire layout."
            ),
            "severity": "high",
            "category": "visual_layout",
        },
        "next_action": {
            "type": "scroll",
            "selector": None,
            "value": "600",
            "reason": "Scroll down to inspect the rest of the page for more issues.",
        },
    },
    # step 1 — after scroll, flag low-contrast text (bug #8)
    {
        "observation": (
            "Below the fold: footer area and caption text are rendered in very light gray "
            "(#c0c0c0) on a white (#ffffff) background. The hero image shows a broken "
            "placeholder — the src asset appears missing."
        ),
        "anomaly": {
            "description": (
                "Footer and caption text uses color #c0c0c0 on white (#ffffff). "
                "Estimated contrast ratio ≈2.3:1 — fails WCAG AA (requires 4.5:1 for normal text)."
            ),
            "severity": "medium",
            "category": "accessibility",
        },
        "next_action": {
            "type": "click",
            "selector": "#submit-btn",
            "value": None,
            "reason": "Click the Submit button to test the form's onclick handler.",
        },
    },
    # step 2 — click submit → JS error (bug #1)
    {
        "observation": (
            "Clicked Submit. The page did not navigate or show a success/error state. "
            "A JavaScript ReferenceError appeared in the browser console: "
            "'handleSubmit is not defined'. The button's onclick attribute calls a "
            "function that was never declared."
        ),
        "anomaly": {
            "description": (
                "Submit button (#submit-btn) onclick='handleSubmit()' calls an undefined function. "
                "Clicking it throws 'ReferenceError: handleSubmit is not defined' in console. "
                "The form is completely non-functional."
            ),
            "severity": "critical",
            "category": "broken_interaction",
        },
        "next_action": {
            "type": "click",
            "selector": "#load-more-btn",
            "value": None,
            "reason": "Test the Load More button which appears disabled but unstyled.",
        },
    },
    # step 3 — Load More click fires handler but it's a silent no-op (bug #5)
    {
        "observation": (
            "Clicked Load More (#load-more-btn). The button is fully styled as active — "
            "same background colour, normal cursor, no 'disabled' attribute. "
            "The click registered and called loadMoreNoOp(), but no content loaded, "
            "no spinner appeared, no error was shown. The page is completely unchanged. "
            "A user would have no indication whether the action succeeded or failed."
        ),
        "anomaly": {
            "description": (
                "'Load More' button (#load-more-btn) looks fully enabled but its onclick "
                "handler loadMoreNoOp() is a deliberate no-op: it fires silently, loads "
                "nothing, and gives zero feedback. Indistinguishable from a working button "
                "to any user."
            ),
            "severity": "medium",
            "category": "broken_interaction",
        },
        "next_action": {
            "type": "click",
            "selector": "#privacy-link",
            "value": None,
            "reason": "Test the Privacy Policy footer link to verify it navigates correctly.",
        },
    },
    # step 4 — privacy link → 404 (bug #4)
    {
        "observation": (
            "Followed the Privacy Policy link (#privacy-link → href=/privacy.html). "
            "The server responded with HTTP 404 Not Found. No page content was returned. "
            "This is a dead link in the footer navigation."
        ),
        "anomaly": {
            "description": (
                "Footer 'Privacy Policy' link (#privacy-link) points to /privacy.html "
                "which returns HTTP 404. The page does not exist — this is a dead link "
                "visible to all users."
            ),
            "severity": "high",
            "category": "dead_link",
        },
        "next_action": {
            "type": "go_back",
            "selector": None,
            "value": None,
            "reason": "Return to main page to inspect the broken image and form label issues.",
        },
    },
    # step 5 — back on page: broken image only (bug #7)
    {
        "observation": (
            "Back on main page. The hero <img id='hero-img'> shows a broken image "
            "placeholder — src '/assets/hero-photo.png' returns 404. "
            "Also noting the login form area for closer inspection next."
        ),
        "anomaly": {
            "description": (
                "Hero image src '/assets/hero-photo.png' returns 404 — the image file "
                "does not exist on the server. All users see a broken image placeholder "
                "instead of the intended hero graphic."
            ),
            "severity": "high",
            "category": "other",
        },
        "next_action": {
            "type": "scroll",
            "selector": None,
            "value": "400",
            "reason": "Scroll to the login form to inspect label/input associations.",
        },
    },
    # step 6 — label/input id mismatch (bug #6), then stop
    {
        "observation": (
            "Login form inspected. The <label for='user-email'> does not match "
            "<input id='email-field'>, and <label for='user-pass'> does not match "
            "<input id='pass-field'>. Screen readers cannot programmatically associate "
            "these labels with their inputs."
        ),
        "anomaly": {
            "description": (
                "Login form label 'for' attributes do not match input 'id' attributes: "
                "<label for='user-email'> vs <input id='email-field'> and "
                "<label for='user-pass'> vs <input id='pass-field'>. "
                "Breaks screen reader label association (WCAG 1.3.1 failure)."
            ),
            "severity": "medium",
            "category": "accessibility",
        },
        "next_action": {
            "type": "stop",
            "selector": None,
            "value": None,
            "reason": (
                "All planned scenarios covered: layout overflow, low-contrast text, "
                "broken submit handler, no-op Load More button, dead link, "
                "broken image, and label/input id mismatch. Stopping the run."
            ),
        },
    },
]


def get_mock_step(step_index: int, url: str, dom_summary: str) -> AgentStep:
    """
    Return a deterministic scripted AgentStep for the given step index.

    Args:
        step_index: Zero-based index of the current agent step.
        url: Current page URL (not used in mock, but matches real signature).
        dom_summary: DOM summary string (not used in mock).

    Returns:
        A fully-valid AgentStep instance.
    """
    if step_index >= len(_SCRIPT):
        return AgentStep(
            observation="Mock script exhausted — all scripted steps completed.",
            anomaly=None,
            next_action=NextAction(
                type="stop",
                selector=None,
                value=None,
                reason="Mock script has no more steps.",
            ),
        )

    entry = _SCRIPT[step_index]

    anomaly: Anomaly | None = None
    if entry.get("anomaly"):
        anomaly = Anomaly(**entry["anomaly"])

    return AgentStep(
        observation=entry["observation"],
        anomaly=anomaly,
        next_action=NextAction(**entry["next_action"]),
    )
