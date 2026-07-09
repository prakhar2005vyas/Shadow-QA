# Shadow QA

**Autonomous visual QA agent powered by Gemma 4 on AMD MI300X + Fireworks AI**

Shadow QA explores a web application like a real user — clicking, filling forms, scrolling — uses a self-hosted multimodal model to *see* the screen, and catches bugs that script-only testers miss: broken buttons, layout breaks, error states, dead links, accessibility problems. Every bug gets a clean, reproducible report.

> Full README coming in Phase 4. Setup, architecture, AMD usage, and Fireworks usage will be documented there.

## Quick Start (Phase 0 — mock mode)

```bash
cp .env.example .env          # edit as needed; MOCK_VLM=true by default
docker compose up --build
# In another terminal:
curl http://localhost:8000/health
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"target_url": "http://fixture-app:80"}'
```

## Architecture

```
Target Web App → Playwright (screenshot, act) ⇄ Gemma 4 on AMD (perceive, decide)
                        │ on anomaly
                        ▼
                  Bug Compiler → Fireworks AI (report writing) → Backend API + SQLite → React Dashboard
```

See [CLAUDE.md](./CLAUDE.md) for the full spec.
