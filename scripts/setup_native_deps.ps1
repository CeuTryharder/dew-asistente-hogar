# Script de Preparación de Dependencias Nativas C++ para Android (llama.cpp + Sherpa-ONNX)
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ThirdPartyDir = Join-Path $ProjectRoot "third_party"
$LlamaCppDir = Join-Path $ThirdPartyDir "llama.cpp"

if (-not (Test-Path $ThirdPartyDir)) {
    New-Item -ItemType Directory -Path $ThirdPartyDir | Out-Null
}

Write-Host "=== [1/2] Configurando motor C++ llama.cpp (con soporte Qwen3.5 / Gated DeltaNet) ===" -ForegroundColor Cyan
if (-not (Test-Path $LlamaCppDir)) {
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git $LlamaCppDir
} else {
    Write-Host "llama.cpp ya está clonado en $LlamaCppDir. Actualizando..." -ForegroundColor Yellow
    Push-Location $LlamaCppDir
    git pull --ff-only
    Pop-Location
}

Write-Host "=== [2/2] Dependencias nativas listas para compilar con CMake / Android NDK ===" -ForegroundColor Green
Write-Host "Ahora puedes abrir el proyecto en Android Studio o compilar el APK con ./gradlew :android_app:assembleDebug"
