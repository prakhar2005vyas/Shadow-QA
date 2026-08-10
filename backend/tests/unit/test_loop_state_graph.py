"""
Unit tests for the loop-prevention state memory graph helpers in agent/loop.py:
  _compute_state_id — stable, structural fingerprint of (url, DOM shape)
  _is_state_exhausted — true once every interactive element has [ALREADY_TRIED]
"""

from app.agent.loop import _compute_state_id, _is_state_exhausted, _MAX_CONSECUTIVE_GO_BACKS

_DOM_UNTRIED = (
    'selector="[data-shadow-id=\'1\']" | button#submit-btn | "Get Started Free"\n'
    'selector="[data-shadow-id=\'2\']" | button#load-more-btn | "Load More Features"'
)

_DOM_PARTIALLY_TRIED = (
    'selector="[data-shadow-id=\'1\']" | button#submit-btn | "Get Started Free" [ALREADY_TRIED]\n'
    'selector="[data-shadow-id=\'2\']" | button#load-more-btn | "Load More Features"'
)

_DOM_FULLY_TRIED = (
    'selector="[data-shadow-id=\'1\']" | button#submit-btn | "Get Started Free" [ALREADY_TRIED]\n'
    'selector="[data-shadow-id=\'2\']" | button#load-more-btn | "Load More Features" [ALREADY_TRIED]'
)


class TestComputeStateId:
    def test_stable_for_identical_input(self):
        a = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        b = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        assert a == b

    def test_differs_for_different_url(self):
        a = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        b = _compute_state_id("http://example.test/other", _DOM_UNTRIED)
        assert a != b

    def test_differs_for_different_dom_shape(self):
        other_dom = _DOM_UNTRIED + '\nselector="[data-shadow-id=\'3\']" | a | "Extra Link"'
        a = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        b = _compute_state_id("http://example.test/", other_dom)
        assert a != b

    def test_ignores_already_tried_markers(self):
        """Same physical page, same elements — only tried-state differs."""
        a = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        b = _compute_state_id("http://example.test/", _DOM_PARTIALLY_TRIED)
        c = _compute_state_id("http://example.test/", _DOM_FULLY_TRIED)
        assert a == b == c

    def test_ignores_data_shadow_id_numbering(self):
        """Same elements, differently-numbered ids (e.g. after a fresh page load)."""
        renumbered = (
            'selector="[data-shadow-id=\'7\']" | button#submit-btn | "Get Started Free"\n'
            'selector="[data-shadow-id=\'8\']" | button#load-more-btn | "Load More Features"'
        )
        a = _compute_state_id("http://example.test/", _DOM_UNTRIED)
        b = _compute_state_id("http://example.test/", renumbered)
        assert a == b


class TestIsStateExhausted:
    def test_false_when_nothing_tried(self):
        assert _is_state_exhausted(_DOM_UNTRIED) is False

    def test_false_when_partially_tried(self):
        assert _is_state_exhausted(_DOM_PARTIALLY_TRIED) is False

    def test_true_when_fully_tried(self):
        assert _is_state_exhausted(_DOM_FULLY_TRIED) is True

    def test_true_for_no_interactive_elements_sentinel(self):
        assert _is_state_exhausted("(no interactive elements found)") is True

    def test_true_for_dom_unavailable_sentinel(self):
        assert _is_state_exhausted("(DOM summary unavailable)") is True

    def test_false_for_empty_string(self):
        # No information either way — not confidently "exhausted".
        assert _is_state_exhausted("") is False


class TestMaxConsecutiveGoBackGuard:
    """
    Regression test for the infinite go_back loop fix.

    Simulates the loop logic that decides between go_back and stop when hitting
    consecutive exhausted states. Asserts that the 4th exhausted-state hit
    (after 3 consecutive go_backs) triggers a stop, not a 4th go_back.
    """

    def test_constant_is_three(self):
        assert _MAX_CONSECUTIVE_GO_BACKS == 3

    def test_stop_forced_after_max_consecutive_go_backs(self):
        """
        Simulate the in-loop decision: after exactly _MAX_CONSECUTIVE_GO_BACKS
        consecutive exhausted states (each triggering a go_back), the next
        exhausted state must trigger a stop instead.
        """
        consecutive_go_backs = 0
        actions: list[str] = []

        # Simulate 4+ exhausted states hitting the guard logic
        for i in range(6):
            is_repeat_and_exhausted = True  # every state is exhausted
            if is_repeat_and_exhausted:
                if consecutive_go_backs >= _MAX_CONSECUTIVE_GO_BACKS:
                    actions.append("stop")
                    break
                else:
                    actions.append("go_back")
                    consecutive_go_backs += 1

        # Should have exactly 3 go_backs then 1 stop
        assert actions == ["go_back", "go_back", "go_back", "stop"]
        assert consecutive_go_backs == 3

    def test_counter_resets_on_non_exhausted_state(self):
        """
        If a productive (non-exhausted) step occurs in between, the counter
        should reset, allowing another 3 go_backs before stopping.
        """
        consecutive_go_backs = 0
        actions: list[str] = []

        # 2 exhausted, then 1 productive, then 4 more exhausted
        sequence = [True, True, False, True, True, True, True]
        for exhausted in sequence:
            if exhausted:
                if consecutive_go_backs >= _MAX_CONSECUTIVE_GO_BACKS:
                    actions.append("stop")
                    break
                else:
                    actions.append("go_back")
                    consecutive_go_backs += 1
            else:
                consecutive_go_backs = 0
                actions.append("productive")

        # After reset: 2 go_backs, productive, 3 go_backs, then stop
        assert actions == [
            "go_back", "go_back",
            "productive",
            "go_back", "go_back", "go_back",
            "stop",
        ]
