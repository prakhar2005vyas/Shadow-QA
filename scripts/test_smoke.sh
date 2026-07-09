#!/usr/bin/env bash
# =============================================================================
# Shadow QA — smoke test
#
# Proves the whole stack boots cleanly from a clean checkout with zero manual
# steps beyond .env: runs `docker compose up`, polls the backend's /health
# endpoint until it returns 200, and tears everything down. This is what a
# grader runs to verify "completeness" in about five minutes.
#
# MOCK_VLM is forced to true here — this script proves the stack boots, it is
# not the Phase 1 real-VLM validation (that's tests/integration/test_vlm_phase1.py,
# run separately against a live AMD droplet or MI300X-equivalent endpoint).
#
# Usage:
#   bash scripts/test_smoke.sh
#
# Exit code 0 = stack booted and /health returned 200. Non-zero = failure,
# with docker compose logs printed for debugging.
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-90}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"

# Ensure a .env exists — docker compose needs it, and .env.example is always
# safe to copy verbatim since MOCK_VLM=true by default (zero GPU/API cost).
if [ ! -f .env ]; then
  echo "==> No .env found — copying .env.example (MOCK_VLM=true, zero manual steps)"
  cp .env.example .env
fi

cleanup() {
  local exit_code=$?
  echo ""
  echo "==> Tearing down..."
  docker compose down --volumes --remove-orphans >/dev/null 2>&1
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

echo "==> Starting stack: docker compose up --build -d (MOCK_VLM=true, zero GPU calls)"
if ! MOCK_VLM=true docker compose up --build -d; then
  echo "FAIL: docker compose up failed to start the stack."
  docker compose logs --tail 100
  exit 1
fi

echo "==> Waiting up to ${TIMEOUT_SECONDS}s for ${HEALTH_URL} to return 200..."
elapsed=0
until curl -sf -o /dev/null "$HEALTH_URL"; do
  if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
    echo "FAIL: ${HEALTH_URL} did not return 200 within ${TIMEOUT_SECONDS}s."
    echo "---- docker compose logs (last 100 lines) ----"
    docker compose logs --tail 100
    exit 1
  fi
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))
done

echo "==> ${HEALTH_URL} responded. Body:"
curl -sf "$HEALTH_URL"
echo ""
echo ""
echo "==> SMOKE TEST PASSED — stack booted cleanly in ~${elapsed}s."
