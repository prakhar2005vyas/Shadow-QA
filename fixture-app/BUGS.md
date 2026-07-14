# Fixture App — Seeded Bugs Answer Key

This directory contains a simple static web application with **9 intentionally seeded bugs**
(`B01`–`B09`). It is used as the target for Shadow QA integration tests and demos.

## Bug Inventory

| # | ID | Category | Severity | Element / Location | Description |
|---|-----|----------|----------|--------------------|-------------|
| 1 | `B01` | `broken_interaction` | critical | `#submit-btn` | `onclick="handleSubmit()"` calls an undefined function → `ReferenceError` in console |
| 2 | `B02` | `error_state` | high | `<form action="/api/contact">` | Form POST target `/api/contact` does not exist → nginx 404 on submit |
| 3 | `B03` | `visual_layout` | high | `.hero` | CSS `width: 120vw` with no `overflow: hidden` on parent → horizontal overflow at all viewports |
| 4 | `B04` | `dead_link` | high | `#privacy-link` | Footer link `href="/privacy.html"` — file does not exist → nginx 404 |
| 5 | `B05` | `broken_interaction` | medium | `#load-more-btn` | `onclick="loadMoreNoOp()"` — button looks fully enabled (no `disabled` attr, full colour, `cursor:pointer`) but click handler is an empty no-op; zero user feedback |
| 6 | `B06` | `accessibility` | medium | `<label for="user-email">` / `<input id="email-field">` | `for` attribute does not match `id` — screen reader cannot associate label with input (WCAG 1.3.1) |
| 7 | `B07` | `other` | high | `#hero-img` | `src="/assets/hero-photo.png"` — file does not exist → broken image placeholder shown |
| 8 | `B08` | `accessibility` | medium | `.caption`, `footer` | Text color `#c0c0c0` on white `#ffffff` background → contrast ratio ≈2.3:1, fails WCAG AA (4.5:1 required) |
| 9 | `B09` | `broken_interaction` | medium | `#export-btn` | `disabled` attribute set but `.btn-primary` has no `:disabled` styling — identical appearance to an active button, clicks silently fail |

## Verification

This fixture seeds **9 bugs** (B01–B09). The deterministic mock VLM
(`backend/app/agent/mock_vlm.py`) is scripted to surface **7 of them** in a
single run — B01, B03, B04, B05, B06, B07, B08 — spanning four categories
(`broken_interaction`, `visual_layout`, `accessibility`, `dead_link`, `other`).
B02 (contact-form 404) and B09 (disabled export button) are intentionally left
for the **real** VLM to find, so mock and real runs aren't identical.

The Phase 0 integration test (`tests/integration/test_fixture_loop.py`) asserts
≥ 3 findings across ≥ 2 categories are produced end-to-end in mock mode.

## What is intentionally correct

- Navigation links to `index.html` (self) work fine
- The page renders structurally valid HTML
- No server-side logic is needed — everything is static HTML/CSS/JS
