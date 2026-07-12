"""
Unit tests for BrowserSession's crash resilience:
  - screenshot_b64(): timeout / protocol-error (OOM'd browser) resilience
  - navigate(): reports unreachable targets instead of silently continuing

Reproduces the reported failure modes via a mocked Page, without launching a
real browser:
  - screenshot: first attempt times out -> retries once with a shorter fallback
    timeout; if the fallback also fails -> returns None instead of raising
  - screenshot: a non-Playwright Exception (simulating a crashed/OOM'd browser
    process surfacing a bare error instead of a clean Playwright one) is caught
    the same way as a PlaywrightError, on both the primary and fallback attempt
  - a successful first attempt never touches the fallback path
  - animations="disabled" is always passed, so screenshots don't wait on CSS animations
  - navigate(): returns True on success, False (never raises) on a Playwright
    navigation error (connection refused, DNS failure) or an unexpected Exception
"""

import base64
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Error as PlaywrightError

from app.agent.browser import BrowserSession


def _session_with_mock_page(screenshot_mock: AsyncMock) -> BrowserSession:
    session = BrowserSession()
    session._page = AsyncMock()
    session._page.screenshot = screenshot_mock
    return session


@pytest.mark.asyncio
async def test_screenshot_success_on_first_attempt_skips_fallback():
    fake_jpeg = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    screenshot_mock = AsyncMock(return_value=fake_jpeg)
    session = _session_with_mock_page(screenshot_mock)

    result = await session.screenshot_b64()

    assert result == base64.b64encode(fake_jpeg).decode()
    assert screenshot_mock.call_count == 1
    _, kwargs = screenshot_mock.call_args
    assert kwargs["animations"] == "disabled"


@pytest.mark.asyncio
async def test_screenshot_falls_back_after_first_timeout():
    fake_jpeg = b"\xff\xd8\xff\xe0fallback-jpeg-bytes"
    screenshot_mock = AsyncMock(
        side_effect=[
            PlaywrightError("Timeout 30000ms exceeded ... waiting for fonts to load"),
            fake_jpeg,
        ]
    )
    session = _session_with_mock_page(screenshot_mock)

    result = await session.screenshot_b64(timeout=30_000, fallback_timeout=5_000)

    assert result == base64.b64encode(fake_jpeg).decode()
    assert screenshot_mock.call_count == 2
    first_kwargs = screenshot_mock.call_args_list[0].kwargs
    second_kwargs = screenshot_mock.call_args_list[1].kwargs
    assert first_kwargs["timeout"] == 30_000
    assert second_kwargs["timeout"] == 5_000


@pytest.mark.asyncio
async def test_screenshot_returns_none_when_both_attempts_time_out():
    screenshot_mock = AsyncMock(
        side_effect=[
            PlaywrightError("Timeout 30000ms exceeded ... waiting for fonts to load"),
            PlaywrightError("Timeout 5000ms exceeded ... waiting for fonts to load"),
        ]
    )
    session = _session_with_mock_page(screenshot_mock)

    result = await session.screenshot_b64()

    assert result is None
    assert screenshot_mock.call_count == 2


@pytest.mark.asyncio
async def test_screenshot_returns_none_on_non_playwright_protocol_error():
    """
    Simulates "Protocol error (Page.captureScreenshot): Unable to capture
    screenshot" from a crashed/OOM'd browser process, surfaced as a bare
    Exception rather than a PlaywrightError. Must be caught on both attempts.
    """
    screenshot_mock = AsyncMock(
        side_effect=[
            RuntimeError(
                "Protocol error (Page.captureScreenshot): Unable to capture screenshot"
            ),
            RuntimeError(
                "Protocol error (Page.captureScreenshot): Unable to capture screenshot"
            ),
        ]
    )
    session = _session_with_mock_page(screenshot_mock)

    result = await session.screenshot_b64()

    assert result is None
    assert screenshot_mock.call_count == 2


@pytest.mark.asyncio
async def test_screenshot_fallback_recovers_from_non_playwright_exception():
    fake_jpeg = b"\xff\xd8\xff\xe0recovered-jpeg-bytes"
    screenshot_mock = AsyncMock(
        side_effect=[RuntimeError("Protocol error: unexpected transport failure"), fake_jpeg]
    )
    session = _session_with_mock_page(screenshot_mock)

    result = await session.screenshot_b64()

    assert result == base64.b64encode(fake_jpeg).decode()
    assert screenshot_mock.call_count == 2


@pytest.mark.asyncio
async def test_navigate_returns_true_on_success():
    session = BrowserSession()
    session._page = AsyncMock()
    session._page.url = "https://example.com/"

    result = await session.navigate("https://example.com")

    assert result is True


@pytest.mark.asyncio
async def test_navigate_returns_false_on_playwright_error():
    session = BrowserSession()
    session._page = AsyncMock()
    session._page.goto = AsyncMock(
        side_effect=PlaywrightError("net::ERR_CONNECTION_REFUSED at http://127.0.0.1:1")
    )

    result = await session.navigate("http://127.0.0.1:1")

    assert result is False


@pytest.mark.asyncio
async def test_navigate_returns_false_on_unexpected_exception():
    session = BrowserSession()
    session._page = AsyncMock()
    session._page.goto = AsyncMock(side_effect=RuntimeError("connection reset by peer"))

    result = await session.navigate("http://127.0.0.1:1")

    assert result is False


@pytest.mark.asyncio
async def test_media_and_font_requests_are_aborted():
    session = BrowserSession()

    for resource_type in ("media", "font"):
        route = AsyncMock()
        route.request.resource_type = resource_type
        await session._handle_route(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    for resource_type in ("image", "document", "script", "stylesheet"):
        route = AsyncMock()
        route.request.resource_type = resource_type
        await session._handle_route(route)
        route.continue_.assert_called_once()
        route.abort.assert_not_called()
