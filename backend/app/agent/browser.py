"""
Playwright browser session wrapper.

Responsibilities:
  - Launch headless Chromium (memory-lean flags, media requests blocked), set viewport
  - Attach listeners: console errors, page errors, failed network requests
  - Take screenshots (returns base64 JPEG)
  - Summarise visible interactive elements (for the DOM summary sent to VLM)
  - Execute NextAction instances (click, fill, scroll, go_back)
  - Graceful error handling: Playwright errors are caught and logged, not re-raised
"""

import asyncio
import base64
import logging
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
)

from .schemas import NextAction

logger = logging.getLogger(__name__)

# Max elements to include in DOM summary (avoids overloading the prompt)
_MAX_ELEMENTS = 30


class BrowserSession:
    def __init__(self, viewport_width: int = 1280, viewport_height: int = 800):
        self._viewport = {"width": viewport_width, "height": viewport_height}
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._console_errors: list[str] = []
        self._network_errors: list[str] = []

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrowserSession":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            # Memory-lean flags for resource-constrained containers (e.g. a 512MB
            # hosting tier). None of these change what the page renders or what the
            # agent can observe — they only strip out background Chromium machinery
            # (GPU compositing, extensions, telemetry, sync, translate, etc.) that
            # a headless single-tab automation session never uses anyway.
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-breakpad",
                "--disable-component-extensions-with-background-pages",
                "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                "--disable-ipc-flooding-protection",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
                "--password-store=basic",
                "--use-mock-keychain",
            ],
        )
        self._context = await self._browser.new_context(viewport=self._viewport)
        self._page = await self._context.new_page()

        # Attach event listeners
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_page_error)
        self._page.on("requestfailed", self._on_request_failed)

        # Block video/audio and web font requests — pure memory/bandwidth/latency
        # cost with zero QA signal. Fonts in particular can hang a page load (a
        # slow/unreachable font CDN makes Page.screenshot()'s implicit "wait for
        # fonts to load" step stall for the full timeout). Images are deliberately
        # NEVER blocked here: broken images are one of the bug categories this
        # agent specifically looks for.
        await self._page.route("**/*", self._handle_route)

        return self

    async def _handle_route(self, route) -> None:
        if route.request.resource_type in ("media", "font"):
            await route.abort()
        else:
            await route.continue_()

    async def __aexit__(self, *args):
        try:
            if self._browser:
                await self._browser.close()
        except Exception as exc:
            logger.debug("Browser close error (ignored): %s", exc)
        try:
            if self._pw:
                await self._pw.stop()
        except Exception as exc:
            logger.debug("Playwright stop error (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    def _on_console(self, msg) -> None:
        if msg.type in ("error", "warning"):
            self._console_errors.append(f"[{msg.type.upper()}] {msg.text}")

    def _on_page_error(self, error) -> None:
        self._console_errors.append(f"[PAGE ERROR] {error}")

    def _on_request_failed(self, request) -> None:
        self._network_errors.append(
            f"[FAILED] {request.method} {request.url} — {request.failure}"
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def console_errors(self) -> list[str]:
        return list(self._console_errors)

    @property
    def network_errors(self) -> list[str]:
        return list(self._network_errors)

    @property
    def current_url(self) -> str:
        return self._page.url if self._page else ""

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def navigate(self, url: str, timeout: float = 15_000) -> None:
        """
        Navigate to a URL. Logs and continues on timeout/error.

        Waits for "load" (all images/stylesheets/iframes fetched) rather than
        "networkidle" — many real sites (ad/analytics-heavy ones especially) never
        actually go network-idle, so networkidle just burns the full timeout on
        every navigation without adding anything the agent can see.
        """
        try:
            await self._page.goto(url, wait_until="load", timeout=timeout)
            logger.info("Navigated to %s", self._page.url)
        except PlaywrightError as exc:
            logger.warning("Navigation to %s failed/timed-out: %s", url, exc)

    async def screenshot_b64(
        self, timeout: float = 30_000, fallback_timeout: float = 5_000
    ) -> Optional[str]:
        """
        Take a viewport screenshot and return as a base64-encoded JPEG string.

        Never raises — a page that hangs Playwright's screenshot call (e.g. one
        still waiting on webfonts, or mid-animation) would otherwise crash the
        whole run with "Timeout 30000ms exceeded ... waiting for fonts to load".
        animations="disabled" skips Playwright's finish-animations-first wait, and
        a single short-timeout retry gives one more chance before giving up. If
        both attempts fail, logs and returns None — the loop skips this step's
        VLM call and moves on rather than crashing.
        """
        try:
            jpeg_bytes = await self._page.screenshot(
                full_page=False,
                type="jpeg",
                quality=70,
                timeout=timeout,
                animations="disabled",
            )
            return base64.b64encode(jpeg_bytes).decode()
        except PlaywrightError as exc:
            logger.warning(
                "screenshot_b64 timed out/failed (timeout=%.0fms): %s — retrying with a %.0fms fallback",
                timeout,
                exc,
                fallback_timeout,
            )
            try:
                jpeg_bytes = await self._page.screenshot(
                    full_page=False,
                    type="jpeg",
                    quality=70,
                    timeout=fallback_timeout,
                    animations="disabled",
                )
                return base64.b64encode(jpeg_bytes).decode()
            except PlaywrightError as exc2:
                logger.error(
                    "screenshot_b64 fallback also failed — continuing without a screenshot: %s",
                    exc2,
                )
                return None

    async def summarize_elements(self, tried_selectors: Optional[set[str]] = None) -> str:
        """
        Return a compact textual summary of visible interactive elements.

        Format: selector="[data-shadow-id='N']" | tag#id.cls[disabled] | "visible text" href
        Each interactive element is stamped with a unique `data-shadow-id` attribute
        (idempotent — assigned once, kept stable across calls on the same page) so the
        selector is guaranteed to match exactly one element. This replaces the previous
        tag/id/class-derived selector, which could collide across multiple elements that
        share the same tag+class (e.g. several `button.btn-primary` with no id) and,
        combined with Playwright's `.first()`, silently redirected clicks to the wrong
        element.

        Elements matching a selector in `tried_selectors` (i.e. already acted on in a
        previous step) are suffixed with " [ALREADY_TRIED]" so the model sees directly
        in the DOM summary what it has already interacted with, instead of having to
        infer it from the separate action-history text.
        """
        try:
            elements: list[str] = await self._page.evaluate(
                f"""(triedSelectors) => {{
                    const sel = 'a[href], button, input, select, textarea, [onclick], [role="button"]';
                    return Array.from(document.querySelectorAll(sel))
                        .slice(0, {_MAX_ELEMENTS})
                        .map(el => {{
                            if (!el.hasAttribute('data-shadow-id')) {{
                                window.__shadowQaIdCounter = (window.__shadowQaIdCounter || 0) + 1;
                                el.setAttribute('data-shadow-id', String(window.__shadowQaIdCounter));
                            }}
                            const shadowId = el.getAttribute('data-shadow-id');
                            const selector = "[data-shadow-id='" + shadowId + "']";
                            const tag  = el.tagName.toLowerCase();
                            const id   = el.id ? '#' + el.id : '';
                            const cls  = el.className
                                ? '.' + String(el.className).trim().split(/\\s+/).join('.')
                                : '';
                            const dis  = el.disabled ? '[disabled]' : '';
                            const label = tag + id + cls + dis;
                            const txt  = (el.innerText || el.value || el.placeholder || el.alt || '')
                                .slice(0, 80).replace(/\\n/g, ' ');
                            const href = el.href ? ' → ' + el.href : '';
                            let tried = false;
                            for (const s of triedSelectors) {{
                                if (!s) continue;
                                try {{ if (el.matches(s)) {{ tried = true; break; }} }} catch (e) {{}}
                            }}
                            const flag = tried ? ' [ALREADY_TRIED]' : '';
                            return 'selector="' + selector + '" | ' + label + ' | "' + txt + '"' + href + flag;
                        }});
                }}""",
                sorted(tried_selectors or []),
            )
            return "\n".join(elements) if elements else "(no interactive elements found)"
        except PlaywrightError as exc:
            logger.warning("summarize_elements failed: %s", exc)
            return "(DOM summary unavailable)"

    async def execute_action(self, action: NextAction) -> str:
        """
        Execute a NextAction via Playwright.
        Returns a human-readable description of what happened.
        Playwright errors are caught and returned as strings — never re-raised.
        """
        try:
            if action.type == "click":
                if not action.selector:
                    return "click action missing selector — skipped"
                # Use JS click to bypass Playwright's enabled-check.
                # This lets us observe what happens when a disabled element is clicked
                # (important for bug #5 — disabled button with no visual feedback).
                try:
                    el = self._page.locator(action.selector).first
                    is_disabled = await el.is_disabled()
                    if is_disabled:
                        await self._page.evaluate(
                            f"document.querySelector({repr(action.selector)}).click()"
                        )
                        await asyncio.sleep(0.3)
                        return f"JS-clicked disabled element {action.selector}"
                    else:
                        await self._page.click(action.selector, timeout=5_000)
                        await asyncio.sleep(0.3)
                        return f"Clicked {action.selector}"
                except PlaywrightError:
                    # If locator fails, fall back to JS click
                    await self._page.evaluate(
                        f"document.querySelector({repr(action.selector)}) && "
                        f"document.querySelector({repr(action.selector)}).click()"
                    )
                    return f"Fallback JS-clicked {action.selector}"

            elif action.type == "fill":
                if not action.selector or action.value is None:
                    return "fill action missing selector or value — skipped"
                await self._page.fill(action.selector, action.value)
                return f"Filled {action.selector!r} with {action.value!r}"

            elif action.type == "scroll":
                distance = int(action.value or 500)
                await self._page.evaluate(f"window.scrollBy(0, {distance})")
                await self._page.wait_for_timeout(400)
                return f"Scrolled {distance}px down"

            elif action.type == "go_back":
                await self._page.go_back(timeout=10_000)
                try:
                    await self._page.wait_for_load_state("load", timeout=8_000)
                except PlaywrightError:
                    pass
                return f"Navigated back to {self._page.url}"

            elif action.type == "stop":
                return "stop"

            else:
                return f"Unknown action type: {action.type!r} — skipped"

        except PlaywrightError as exc:
            logger.warning(
                "Action %s on %r failed (stale selector or navigation error): %s",
                action.type,
                action.selector,
                exc,
            )
            return f"Action failed gracefully: {exc}"
        except Exception as exc:
            logger.warning("Unexpected error executing action %s: %s", action.type, exc)
            return f"Action error: {exc}"
