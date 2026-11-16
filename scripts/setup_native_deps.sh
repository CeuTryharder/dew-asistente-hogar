#!/usr/bin/env bash
# Script de Preparación de Dependencias Nativas C++ para Android (llama.cpp + Sherpa-ONNX)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY_DIR="${PROJECT_ROOT}/third_party"
LLAMA_CPP_DIR="${THIRD_PARTY_DIR}/llama.cpp"

mkdir -p "${THIRD_PARTY_DIR}"

echo "=== [1/2] Configurando motor C++ llama.cpp (con soporte Qwen3.5 / Gated DeltaNet) ==="
if [ ! -d "${LLAMA_CPP_DIR}" ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "${LLAMA_CPP_DIR}"
else
  echo "llama.cpp ya existe en ${LLAMA_CPP_DIR}. Actualizando..."
  git -C "${LLAMA_CPP_DIR}" pull --ff-only
fi

echo "=== [2/2] Dependencias nativas listas para compilar con CMake / Android NDK ==="
echo "Ejecuta ./gradlew :android_app:assembleDebug para generar el APK."
