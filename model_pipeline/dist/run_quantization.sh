#!/usr/bin/env bash
# Script Automático de Calibración y Cuantización para Dew (Bash)
set -euo pipefail
DIST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${DIST_DIR}/../.." && pwd)"
BASE_GGUF="${REPO_ROOT}/model_pipeline/base_weights/Qwen3.8-9B-Distill-f16.gguf"

if [ ! -f "${BASE_GGUF}" ]; then
  echo "Descargando modelo base desde Hugging Face (empero-ai/Qwen3.8-9B-Distill-GGUF)..."
  huggingface-cli download empero-ai/Qwen3.8-9B-Distill-GGUF --local-dir "$(dirname "${BASE_GGUF}")"
fi

echo "=== [1/4] Calculando imatrix en español doméstico ==="
llama-imatrix -m "${REPO_ROOT}/model_pipeline/base_weights/Qwen3.8-9B-Distill-f16.gguf" -f "${REPO_ROOT}/model_pipeline/corpus/generated/dew_calibration_es.txt" -o "${DIST_DIR}/dew_qwen38_es.imatrix" -t 8 -ngl 99 --ctx-size 2048 --chunks 120

echo "=== [2/4] Cuantizando Edición Compacta 8 GB RAM (IQ3_XXS) ==="
llama-quantize --imatrix "${DIST_DIR}/dew_qwen38_es.imatrix" --token-embd-type q4_k --output-tensor-type q5_k "${REPO_ROOT}/model_pipeline/base_weights/Qwen3.8-9B-Distill-f16.gguf" "${DIST_DIR}/dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf" IQ3_XXS 8

echo "=== [3/4] Cuantizando Edición Pro 12 GB+ RAM (Q4_K_M) ==="
llama-quantize --imatrix "${DIST_DIR}/dew_qwen38_es.imatrix" --token-embd-type q5_k --output-tensor-type q6_k "${REPO_ROOT}/model_pipeline/base_weights/Qwen3.8-9B-Distill-f16.gguf" "${DIST_DIR}/dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf" Q4_K_M 8

echo "=== [4/4] Precomputando sesiones de Prompt Cache ==="
llama-cli -m "${DIST_DIR}/dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf" -f "${DIST_DIR}/dew_system_prefix.txt" --prompt-cache "${DIST_DIR}/dew_system_prompt_8gb.session" --prompt-cache-all -n 1 --ctx-size 4096 -ctk q8_0 -ctv q4_0
llama-cli -m "${DIST_DIR}/dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf" -f "${DIST_DIR}/dew_system_prefix.txt" --prompt-cache "${DIST_DIR}/dew_system_prompt_12gb.session" --prompt-cache-all -n 1 --ctx-size 4096 -ctk q8_0 -ctv q4_0

echo "=== Empaquetado finalizado con éxito ==="
