#!/usr/bin/env bash
# =============================================================================
# Shadow QA — local Ollama startup script
#
# Starts Ollama as a Docker container and pulls the configured model.
# Reads VLM_MODEL_ID from the environment (or .env) so the script and
# .env can never drift apart — the model ID is the single source of truth.
#
# Requirements:
#   - Docker running locally
#   - VLM_MODEL_ID set in env or .env (e.g. gemma4:e2b)
#
# Usage:
#   source .env && bash scripts/start_ollama.sh
#
# After "Ollama is running", update your .env:
#   MOCK_VLM=false
#   VLM_BASE_URL=http://host.docker.internal:11434/v1   # from inside Docker
#   # OR for native host access:
#   VLM_BASE_URL=http://localhost:11434/v1
#   VLM_API_KEY=ollama      # Ollama ignores this value but the field must be non-empty
#   VLM_MODEL_ID=<same value you set below>
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Read model from environment — never hardcode it here.
# VLM_MODEL_ID must be set before calling this script (via .env or export).
# ---------------------------------------------------------------------------
: "${VLM_MODEL_ID:?VLM_MODEL_ID must be set (e.g. export VLM_MODEL_ID=gemma4:e2b)}"

MODEL="$VLM_MODEL_ID"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
OLLAMA_DATA="${OLLAMA_DATA:-$HOME/.ollama}"

echo "==> Model:   $MODEL"
echo "==> Port:    $OLLAMA_PORT"
echo "==> Data:    $OLLAMA_DATA"

# ---------------------------------------------------------------------------
# Start the Ollama container if not already running
# ---------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q '^shadow-qa-ollama$'; then
  echo "==> Ollama container already running, skipping docker run."
else
  echo "==> Starting Ollama container..."
  docker run -d \
    --name shadow-qa-ollama \
    --restart unless-stopped \
    -p "${OLLAMA_PORT}:11434" \
    -v "${OLLAMA_DATA}:/root/.ollama" \
    ollama/ollama
  echo "==> Waiting for Ollama to start..."
  sleep 3
fi

# ---------------------------------------------------------------------------
# Pull the model (idempotent — safe to re-run)
# ---------------------------------------------------------------------------
echo "==> Pulling model: $MODEL  (this can take a while on first run)"
docker exec shadow-qa-ollama ollama pull "$MODEL"

# ---------------------------------------------------------------------------
# Verify the model is listed
# ---------------------------------------------------------------------------
echo "==> Verifying model is available..."
docker exec shadow-qa-ollama ollama list | grep "$MODEL" \
  && echo "==> Model ready: $MODEL" \
  || { echo "ERROR: model '$MODEL' not found after pull"; exit 1; }

echo ""
echo "==> Ollama is running on port ${OLLAMA_PORT}."
echo "==> Set in .env:"
echo "    MOCK_VLM=false"
echo "    VLM_BASE_URL=http://host.docker.internal:${OLLAMA_PORT}/v1"
echo "    VLM_MODEL_ID=${MODEL}"
echo "    VLM_API_KEY=ollama"
echo ""
echo "==> Then: docker compose up -d && docker compose exec backend pytest tests/integration/test_vlm_phase1.py -v -s"
