#!/usr/bin/env bash
# =============================================================================
# Shadow QA — vLLM startup script for AMD MI300X (ROCm)
#
# Run this on the AMD droplet BEFORE pointing VLM_BASE_URL at it.
#
# Requirements on the droplet:
#   - Docker installed and running
#   - /dev/kfd and /dev/dri/renderD* present (ROCm GPU device nodes)
#   - At least ~60 GB free disk (model + Chromium cache)
#   - A Hugging Face token with access to google/gemma-4-26B-A4B-it
#     (request access at https://huggingface.co/google/gemma-4-26B-A4B-it)
#
# Usage:
#   export HF_TOKEN=hf_xxxx
#   bash scripts/start_vlm_rocm.sh
#
# After the server prints "Application startup complete", set in your .env:
#   MOCK_VLM=false
#   VLM_BASE_URL=http://<droplet-ip>:8000/v1
#   VLM_MODEL_ID=google/gemma-4-26B-A4B-it
#   VLM_API_KEY=changeme          # any non-empty string; vLLM ignores it unless --api-key is set
# =============================================================================

set -euo pipefail

: "${HF_TOKEN:?HF_TOKEN must be set — get it from https://huggingface.co/settings/tokens}"
: "${VLM_MODEL_ID:?VLM_MODEL_ID must be set (e.g. export VLM_MODEL_ID=google/gemma-4-26B-A4B-it)}"

MODEL="$VLM_MODEL_ID"
PORT="${VLM_PORT:-8000}"
HF_CACHE="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"

echo "==> Starting vLLM with model: $MODEL"
echo "==> Listening on port: $PORT"
echo "==> HF cache: $HF_CACHE"

# Create cache dir if missing
mkdir -p "$HF_CACHE"

docker run --rm \
  --name shadow-qa-vlm \
  --device /dev/kfd \
  --device /dev/dri \
  --group-add video \
  --ipc host \
  --shm-size 16g \
  -p "${PORT}:8000" \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  -e "HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}" \
  vllm/vllm-openai-rocm:gemma4 \
    --model "${MODEL}" \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --tensor-parallel-size 1 \
    --dtype bfloat16 \
    --enable-prefix-caching \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8000

# Note: guided_json (structured decoding) is enabled by default in vLLM ≥0.4.
# Shadow QA passes guided_json=<AgentStep JSON schema> in every chat/completions
# request to guarantee valid structured output from Gemma 4.
