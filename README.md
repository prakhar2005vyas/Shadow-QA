# Shadow QA

**Autonomous visual QA agent — Gemma 4 on Ollama Cloud + Fireworks AI reporting**

Shadow QA is pointed at a URL and explores it like a real user would: clicking buttons, filling
forms, scrolling, following links. A multimodal model *sees* the screen at every step and catches
the kind of bugs a script-only tester misses — broken buttons, layout breaks, error states, dead
links, accessibility problems, and silent JS/network failures that produce no visible change on
the page at all. Every anomaly it finds becomes a clean, reproducible bug report with a screenshot
and plain-English repro steps.

Built for Track 3 ("Unicorn") of the AMD Developer Hackathon: ACT II.

---

## Table of contents

- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Architecture](#architecture)
- [The VLM backend — Ollama Cloud](#the-vlm-backend--ollama-cloud)
- [Fireworks AI — used separately, for reporting only](#fireworks-ai--used-separately-for-reporting-only)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Security](#security)
- [Known gaps / next steps](#known-gaps--next-steps)

---

## Quick start

Requirements: Docker + Docker Compose. Nothing else — Playwright's browser, Python deps, and the
frontend build all happen inside the containers.

```bash
git clone <this-repo-url> shadow-qa
cd shadow-qa
cp .env.example .env        # defaults to MOCK_VLM=true — zero GPU/API cost
docker compose up --build
```

That's the entire setup. No manual dependency installs, no separate frontend build step, no
database migrations to run by hand.

Once the stack is up:

- **Dashboard:** http://localhost:5173
- **Backend API:** http://localhost:8000 (docs at `/docs`)
- **Bundled fixture app** (a deliberately-broken demo target — see
  [`fixture-app/BUGS.md`](fixture-app/BUGS.md) for its answer key): http://localhost:8080

Start a run either from the dashboard's "Start a New Run" form, or directly against the API:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com"}'
```

> The bundled `fixture-app` is only reachable target-URL-wise from *inside* the Docker network
> (test code that calls the agent loop directly uses it that way). Submitting `http://fixture-app:80`
> through the public API/dashboard will be rejected by the [SSRF guard](#security), because Docker's
> bridge-network address for that container falls inside a blocked private range — this is the
> guard working as intended, not a bug. To try the dashboard end-to-end, point it at a real public
> URL, e.g. `https://example.com`.

### Smoke test

```bash
bash scripts/test_smoke.sh
```

Runs `docker compose up --build`, polls `/health` until it returns 200, prints the response, and
tears the stack down (`docker compose down --volumes`) — success or failure. This is what proves
"boots cleanly with zero manual steps" in about five minutes; a grader can run this one script and
get a pass/fail answer without reading anything else. It forces `MOCK_VLM=true`, so it costs zero
GPU/API calls regardless of what's in your `.env`.

---

## Environment variables

Copy `.env.example` to `.env` and fill in what you need — `.env` is gitignored and never committed.

```bash
# ---------- VLM / Vision-Decision layer (Ollama Cloud) ----------
MOCK_VLM=true                                   # true = zero-cost deterministic mock loop (default)
VLM_BASE_URL=http://host.docker.internal:11434/v1   # Ollama Cloud, OpenAI-compatible endpoint
VLM_MODEL_ID=gemma4:31b-cloud                   # never hardcoded — swap models in one line
VLM_API_KEY=ollama                              # Ollama Cloud API key

# ---------- Fireworks AI (report-writing step ONLY) ----------
FIREWORKS_API_KEY=                              # empty = Fireworks client returns a stub report
FIREWORKS_MODEL_ID=accounts/fireworks/models/llama-v3p3-70b-instruct

# ---------- Agent budget ----------
MAX_STEPS_PER_RUN=20
MAX_SECONDS_PER_RUN=240                         # bump for slower/cloud model endpoints

# ---------- Database ----------
DATABASE_URL=sqlite:///./shadowqa.db           # set to a Neon postgres:// URL in production
```

`MOCK_VLM=true` is the default and is all you need to see the full loop, dashboard, and reporting
pipeline end-to-end at zero cost. Flip it to `false` and point `VLM_BASE_URL` at your Ollama Cloud
endpoint to run the agent for real — see
[The VLM backend — Ollama Cloud](#the-vlm-backend--ollama-cloud) below.

---

## Architecture

```
Target Web App → Playwright (screenshot, act) ⇄ Gemma 4 (perceive, decide next_action)
                        │ on anomaly
                        ▼
                  Bug Compiler → Fireworks AI (report writing) → Backend API + SQLite → React Dashboard
```

**The loop**, once per run:

1. Launch headless Chromium (Playwright), navigate to the target URL, set the viewport.
2. Attach listeners for console errors, page errors, and failed network requests — these run for
   the whole session, not just at anomaly time.
3. Loop until `MAX_STEPS_PER_RUN` or `MAX_SECONDS_PER_RUN` is hit, whichever comes first:
   - Screenshot the page.
   - Summarize visible interactive elements — each one gets a unique, stable `data-shadow-id`
     selector stamped onto it, so the model always has an unambiguous element to reference even
     when several elements share the same tag/class.
   - Call the VLM with the screenshot, the DOM summary, the goal, the action history, previously
     reported anomalies (so it doesn't re-report the same persistent bug every step), and any new
     console/network errors since the last action — many real bugs (a JS `ReferenceError`, a form
     POST that 404s) are completely invisible in a screenshot, so this is fed in as ground truth
     alongside the image.
   - The model responds with structured JSON: `{ observation, anomaly (nullable), next_action }`.
   - Every step is persisted (not just anomaly ones), so the dashboard's live view can poll
     step-by-step progress while a run is still in flight.
   - If an anomaly was flagged, record a `Finding`: screenshot, console/network snapshot, action
     trail leading up to it.
   - Execute `next_action` via Playwright — click, fill, scroll, go back, or stop. Failures (stale
     selector, navigation error) are caught and logged, never crash the run.
4. Compile every `Finding` into a polished bug report via Fireworks AI (see below).
5. Persist the run, findings, and reports; the dashboard reflects the final state.

**Structured output.** The VLM is called with a JSON `response_format` constraint (the
OpenAI-compatible JSON mode Ollama Cloud supports) so its response is valid JSON matching
the `AgentStep` schema — no free-text parsing, no flaky regexes. A markdown-fence/embedded-JSON
fallback parser exists for the rare case a model adds decoration despite the constraint.

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

**Stack:**

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLModel + SQLite, httpx, tenacity |
| Browser automation | Playwright (Python), headless Chromium |
| Vision/decision model | Gemma 4 26B-MoE, OpenAI-compatible chat completions API |
| Report writing | Fireworks AI, OpenAI-compatible endpoint |
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Containers | Docker Compose — backend, frontend, fixture-app. The model server runs separately, reached over HTTP via `VLM_BASE_URL` |

---

## The VLM backend — Ollama Cloud

The vision/decision step of the agent loop — the model that looks at each screenshot and decides
what's broken and what to do next — runs on **Ollama Cloud**, an OpenAI-compatible hosted endpoint.
The integration is enforced in code: `vlm_client.py` is the *only* file that ever calls the
vision/decision model, and it always reads the endpoint from `VLM_BASE_URL` rather than hardcoding
anything.

**The production path:**

- **Provider:** [Ollama Cloud](https://ollama.com/) — OpenAI-compatible chat-completions API.
- **Model:** Gemma 4 (`gemma4:31b-cloud`) — the model ID is always an env var (`VLM_MODEL_ID`),
  never hardcoded, so it can be swapped to any other vision-capable model in one change.
- **Structured decoding:** the OpenAI-compatible `response_format` (JSON mode) forces the model to
  return valid JSON matching the `AgentStep` schema, backed by a defensive markdown-fence/embedded-JSON
  fallback parser — no reliance on prompt-only compliance.
- **Config:** flip `MOCK_VLM=false` and set:
  ```
  MOCK_VLM=false
  VLM_BASE_URL=http://host.docker.internal:11434/v1
  VLM_MODEL_ID=gemma4:31b-cloud
  VLM_API_KEY=ollama
  ```
  Then validate against the bundled fixture app with `docker compose exec backend pytest
  tests/integration/test_vlm_phase1.py -v -s`.

**Deployment.** The backend (this VLM client, Playwright, the API, SQLite/Neon) runs on the
**Render free tier (512MB RAM)**; the frontend is on Vercel. Playwright's Chromium is tuned for that
512MB ceiling (see `backend/app/agent/browser.py`): site-isolation disabled, a single renderer
process, a capped V8 heap, media/font requests blocked, JPEG screenshots, and single-tab enforcement.

> **Note on AMD:** this project was built for the AMD Developer Hackathon (Track 3). An earlier
> design targeted self-hosted Gemma 4 on an AMD MI300X via vLLM/ROCm, and `scripts/start_vlm_rocm.sh`
> remains in the repo as an optional way to run that path. The **final production architecture
> deliberately uses Ollama Cloud instead** — a decision that trades away the AMD hardware-usage bonus
> in exchange for a zero-provisioning, always-available hosted backend.

---

## Fireworks AI — used separately, for reporting only

Fireworks AI is used for exactly one thing: turning a `Finding` (a raw anomaly description +
severity + category + action trail) into a polished, human-readable markdown bug report. It is
**never** involved in perceiving the screen or deciding what the agent does next — that's the
Ollama Cloud VLM path above, and the two are kept structurally separate:

- `backend/app/agent/vlm_client.py` — the *only* place the vision/decision model is called.
- `backend/app/reporting/fireworks_client.py` — the *only* place Fireworks AI is called.

`compiler.py` calls `fireworks_client.generate_report_text()` once per `Finding` after a run
completes, with the OpenAI-compatible endpoint `https://api.fireworks.ai/inference/v1` and model
ID `accounts/fireworks/models/llama-v3p3-70b-instruct` (also an env var, `FIREWORKS_MODEL_ID`). If
`FIREWORKS_API_KEY` is unset, it returns a labeled stub report instead of failing — this is what
lets the full pipeline run end-to-end with zero external API calls in `MOCK_VLM=true` mode and in
all automated tests.

---

## Repository layout

```
shadow-qa/
├── CLAUDE.md                     # full project spec
├── README.md
├── LICENSE                       # MIT
├── .env.example
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py             # SQLModel: Run, Step, Finding, Report
│   │   ├── agent/                # loop.py, browser.py, vlm_client.py, schemas.py, mock_vlm.py
│   │   ├── reporting/            # compiler.py, fireworks_client.py
│   │   ├── security/             # url_guard.py — SSRF guard
│   │   └── routes/                # health.py, vlm_health.py, runs.py
│   └── tests/
│       ├── unit/
│       └── integration/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── components/           # RunForm, LiveAgentView, ReportView, SeverityBadge
│       └── hooks/                # useRuns, useSteps
├── fixture-app/                  # intentionally-broken demo target
│   └── BUGS.md                   # answer key for the seeded bugs
└── scripts/
    ├── start_vlm_rocm.sh         # OPTIONAL/legacy: self-host on AMD MI300X (not the production path)
    ├── start_ollama.sh           # local/interim model serving for dev iteration
    └── test_smoke.sh             # docker compose up → /health → teardown
```

---

## Testing

```bash
# Unit + mock-mode integration tests (zero GPU/API cost, no real network calls)
docker compose run --rm -e MOCK_VLM=true backend \
  python -m pytest tests/unit tests/integration/test_fixture_loop.py -v

# Real-VLM validation (requires a live endpoint — see "The VLM backend" above)
docker compose exec backend pytest tests/integration/test_vlm_phase1.py -v -s
```

Coverage:

- **Unit:** VLM response schema parsing/validation, the SSRF URL guard, the bug compiler
  (mocking `fireworks_client` — no real Fireworks calls in unit tests), the step/screenshot API
  routes.
- **Integration (mock mode):** the full perceive-decide-act loop end-to-end against the bundled
  `fixture-app`, asserting it flags a minimum number of the seeded bugs across multiple categories,
  every `Step` is persisted with a screenshot, and every `Finding` gets a compiled `Report`.
- **Integration (real VLM):** the same loop against a live endpoint, asserting it finds most of the
  bugs catalogued in `fixture-app/BUGS.md`.
- **Smoke:** `scripts/test_smoke.sh` — full `docker compose up` → `/health` → teardown.

Real Ollama Cloud or Fireworks endpoints are never called from unit tests or CI — `MOCK_VLM=true` and a stub
Fireworks client cover that path.

---

## Security

- **SSRF guard** (`backend/app/security/url_guard.py`): every submitted target URL has its hostname
  DNS-resolved, then every resolved IP is checked against blocked ranges — loopback, private,
  link-local/cloud-metadata, carrier-grade NAT, this-network, and their IPv6 equivalents. This is
  resolve-then-check, not string-match-then-check, specifically to prevent bypasses like decimal-
  encoded IPs or DNS rebinding. Only `http`/`https` schemes are allowed. Enforced in
  `routes/runs.py` before a run is ever persisted or Playwright ever navigates.
- **Budgets:** every run is bounded by both a step count (`MAX_STEPS_PER_RUN`) and a wall-clock
  timeout (`MAX_SECONDS_PER_RUN`) — whichever is hit first stops the loop cleanly.
- **Timeouts + retries:** every VLM and Fireworks call has an explicit timeout and limited
  exponential-backoff retries (`tenacity`). On repeated failure, that step (or report) is marked
  inconclusive and the run continues rather than crashing.

---

## Known gaps / next steps

- The bundled `fixture-app` can't be targeted through the public dashboard/API (only from test code
  calling the agent loop directly) because its Docker-internal address falls inside the SSRF
  guard's blocked private-IP range — this is expected, not a bug, but worth knowing when demoing.
