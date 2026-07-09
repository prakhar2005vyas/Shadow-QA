# Shadow QA — Project Spec

## Mission

Build **Shadow QA**: an autonomous agent that is pointed at a URL, explores it like a user would (clicking, filling forms, scrolling), and uses a self-hosted multimodal model to *see* the screen and catch bugs a script-only tester would miss — broken buttons, layout breaks, error states, dead links, accessibility problems. For every bug found, it produces a clean, reproducible report.

This is for Track 3 ("Unicorn") of the AMD Developer Hackathon: ACT II. Judging weighs creativity, originality, **completeness**, **use of AMD platforms**, and product/market potential — not raw benchmarks. Build and pitch this as a product, not a demo script.

## Hard constraints — do not violate these

- Submission deadline: **July 11, 2026, 9:30 PM IST**. Work backward from that.
- Everything must run via `docker compose up` from a clean checkout. No manual steps a grader would have to guess.
- ~~The vision/decision model (Gemma) **must run self-hosted on AMD hardware** (vLLM on an MI300X droplet) — never proxied through a third-party API. This is required for hackathon bonus eligibility.~~
  **AMENDED 2026-07-09:** Ollama Cloud (e.g. a `-cloud` suffixed model such as the 31b model used in Phase 1 testing) is now an accepted backend for `VLM_BASE_URL`, alongside self-hosted vLLM on AMD MI300X. This was changed to unblock Phase 1 testing. Explicitly noting the tradeoff: this drops the "self-hosted on AMD, never a third-party API" requirement, which the original constraint tied directly to hackathon bonus eligibility — using Ollama Cloud for the actual submission is expected to forfeit that bonus. If AMD bonus eligibility is still wanted for the final submission, the real MI300X/vLLM endpoint must be used for the demo/submission run, not Ollama Cloud.
- **Fireworks AI is used only for the text report-writing step, never for the vision/decision step.** Keep this separation clean and visible in the code and the README.
- GPU credits are limited (~50 hours total). Everything except the actual vision call must work in a `MOCK_VLM=true` mode that costs zero GPU time — real GPU calls are reserved for integration testing and the demo.
- Never commit secrets. `.env` is gitignored; `.env.example` ships with placeholders for every variable.
- If a `frontend/index.html` already exists in this directory from earlier work, inspect it and build on it rather than overwriting it, unless it's an empty placeholder.

## Tech stack — decided, do not re-litigate

- **Backend:** Python 3.11, FastAPI, Pydantic v2, SQLModel + SQLite, httpx, tenacity for retries.
- **Browser automation:** Playwright (Python), headless Chromium.
- **Vision/decision model:** Gemma 4 26B-MoE (`google/gemma-4-26B-A4B-it`), served via vLLM's OpenAI-compatible server on an AMD MI300X droplet (ROCm image `vllm/vllm-openai-rocm:gemma4`). The model id is an env var (`VLM_MODEL_ID`) — never hardcoded, so it can be swapped (e.g. to `google/gemma-3-27b-it`) in one change if needed.
- **Report writing:** Fireworks AI, OpenAI-compatible endpoint (`https://api.fireworks.ai/inference/v1`), default model `accounts/fireworks/models/llama-v3p3-70b-instruct` (also an env var).
- **Frontend:** React + Vite + TypeScript + Tailwind.
- **Containers:** Docker Compose for backend + frontend + fixture-app. The GPU model server runs separately on the AMD droplet, reached over HTTP via `VLM_BASE_URL`.

## Architecture & the core loop

```
Target Web App → Playwright (screenshot, act) ⇄ Gemma 4 on AMD (perceive, decide next_action)
                        │ on anomaly
                        ▼
                  Bug Compiler → Fireworks AI (report writing) → Backend API + SQLite → React Dashboard
```

Loop:
```
for each run:
  1. launch Playwright, navigate to target, set viewport
  2. attach listeners: console errors, page errors, failed network requests
  3. loop until MAX_STEPS or MAX_SECONDS is hit:
       a. screenshot the page
       b. summarize visible interactive elements (buttons/links/inputs + selectors)
       c. call Gemma 4 (image + DOM summary + goal + action history)
          → structured JSON: { observation, anomaly (nullable), next_action }
       d. if anomaly: record a Finding (screenshot, console/network snapshot, action trail)
       e. execute next_action via Playwright (fail gracefully if the selector is stale)
       f. stop if next_action.type == "stop" or the budget is exceeded
  4. compile Findings → one Fireworks call per finding → structured bug report
  5. persist run + findings + reports; return run_id to the frontend
```

VLM structured-output schema (implement close to this):

```python
class NextAction(BaseModel):
    type: Literal["click", "fill", "scroll", "go_back", "stop"]
    selector: str | None
    value: str | None
    reason: str

class Anomaly(BaseModel):
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal["broken_interaction", "visual_layout", "accessibility", "error_state", "dead_link", "other"]

class AgentStep(BaseModel):
    observation: str
    anomaly: Anomaly | None
    next_action: NextAction
```

Use vLLM's structured/guided-decoding support to force valid JSON from the model rather than parsing free text (check vLLM's current docs for the exact flag). Do not skip this — it's the difference between a robust loop and a flaky one.

## Repository layout

```
shadow-qa/
├── CLAUDE.md
├── README.md
├── LICENSE                      # MIT
├── .env.example
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models.py            # SQLModel: Run, Finding, Report
│   │   ├── agent/                # loop.py, browser.py, vlm_client.py, schemas.py, mock_vlm.py
│   │   ├── reporting/            # compiler.py, fireworks_client.py
│   │   ├── security/             # url_guard.py — SSRF guard
│   │   └── routes/
│   └── tests/
│       ├── unit/
│       └── integration/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── index.html
│   └── src/
├── fixture-app/                  # intentionally-broken demo target
│   └── BUGS.md                   # answer key for the seeded bugs
```

## Environment variables (`.env.example` — commit this, never commit `.env`)

```
MOCK_VLM=true
VLM_BASE_URL=http://<droplet-ip>:8000/v1
VLM_MODEL_ID=google/gemma-4-26B-A4B-it
VLM_API_KEY=changeme
FIREWORKS_API_KEY=
FIREWORKS_MODEL_ID=accounts/fireworks/models/llama-v3p3-70b-instruct
MAX_STEPS_PER_RUN=20
MAX_SECONDS_PER_RUN=240
DATABASE_URL=sqlite:///./shadowqa.db
```

## Build order — work through these phases IN ORDER

**After each phase: run that phase's tests, show the results and how to see it running, and wait for explicit go-ahead before starting the next phase. Do not skip ahead or bundle phases together.**

### Phase 0 — Skeleton + fixture app + mock mode
Scaffold the repo per the layout above. Build `fixture-app/` with at least 6 seeded, categorized bugs (mix of: dead click handler, layout overflow at mobile width, uncaught JS error on submit, broken image, low-contrast text, 404 link) plus `BUGS.md` as the answer key. Implement `mock_vlm.py` returning deterministic/scripted decisions. Get the full loop running end-to-end against the fixture app with `MOCK_VLM=true`, via `docker compose up`.
**Done when:** `docker compose up` boots cleanly; a run against the fixture app completes and produces findings, using zero GPU calls.

### Phase 1 — Real Gemma 4 on AMD
Stand up the MI300X droplet (vLLM Quick Start / ROCm image), serve `google/gemma-4-26B-A4B-it`, and point `vlm_client.py` at it for real (flip `MOCK_VLM=false`). Validate against the fixture app.
**Done when:** a real run against the fixture app finds most of the seeded bugs in `BUGS.md`.

### Phase 2 — Reporting + hardening
Wire in `fireworks_client.py` and `compiler.py` so every Finding becomes a structured report. Add console/network capture to the browser layer. Implement the SSRF guard, the step/time budget, and timeouts+retries on both model calls.
**Done when:** a run produces human-readable reports end to end, and the SSRF guard has its own passing unit test.

### Phase 3 — Frontend + integration tests
Build the dashboard: a form to submit a URL, a live agent view (screenshots + running commentary as the loop executes), and a final report view. Write the integration test that runs the full loop against `fixture-app/` and asserts it flags at least N of the seeded bugs. Run the pipeline against 1–2 real external sites for variety.
**Done when:** the integration test passes in CI-like conditions (mock VLM is fine there), and the UI shows a run start-to-finish.

### Phase 4 — Package for submission
Write the README (setup, run, architecture, an explicit "How we used AMD" section naming MI300X/ROCm/vLLM/self-hosted Gemma 4, and how Fireworks is used separately). Add the MIT `LICENSE`. Confirm `docker compose up` works from a completely clean checkout. Prepare whatever the submission form needs (demo video, cover image, hosted URL).
**Done when:** a clean checkout, on a machine that has never seen this repo, runs with zero manual steps beyond filling in `.env`.

## Testing bar — non-negotiable at every phase

- Unit tests for: the VLM response schema parsing/validation, the SSRF url guard, the bug compiler.
- One integration test that runs the full loop (mock VLM is fine) against `fixture-app/` and asserts it flags at least N of the seeded bugs.
- A smoke test script that runs `docker compose up`, waits for a `/health` endpoint, hits it, and tears down — this is what proves "completeness" to a grader in five minutes.
- Run the relevant tests before reporting a phase done. If something fails, fix it before moving on. Do not leave known-broken code and proceed to the next phase.

## Security & robustness requirements

- **SSRF guard:** resolve the hostname of every submitted target URL and reject private/loopback/link-local/metadata-service IP ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`) before Playwright ever navigates there. Allow only `http`/`https` schemes. Resolve-then-check, not string-match-then-check, to avoid trivial bypasses.
- Both a step-count budget and a wall-clock budget per run (env-configurable); whichever is hit first stops the loop cleanly.
- Timeout + limited retries (exponential backoff) on every VLM and Fireworks call. On repeated failure, mark that step "inconclusive" and continue rather than crashing the whole run.

## Definition of done for the whole project

- `docker compose up` on a clean checkout works with no manual steps beyond `.env`.
- A full run against `fixture-app/` completes and the report lists most seeded bugs, each with a screenshot and plain-English repro steps.
- The same pipeline runs against at least one real external URL without crashing.
- README explicitly documents the AMD usage and the Fireworks usage as separate, distinct steps.
- `LICENSE` file (MIT) present at repo root.

## Things you must NOT do

- Don't call the real AMD or Fireworks endpoints from unit tests — use `MOCK_VLM=true` / a stub client.
- Don't let the agent navigate anywhere the SSRF guard would reject, even during manual testing — test the guard itself with unit tests instead.
- Don't silently swallow errors — log them, and surface a clear "inconclusive" state in the report rather than pretending a step succeeded.
- Don't add multi-user auth or other scope creep — this is a single-tenant hackathon demo, not a multi-tenant product.
- Don't hardcode model ids, endpoints, or credentials — everything model/endpoint-related is an env var.
