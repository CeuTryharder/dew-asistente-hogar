# Script Automático de Calibración y Cuantización para Dew (PowerShell)
# Modelo base: empero-ai/Qwen3.8-9B-Distill (Apache 2.0)
$ErrorActionPreference = 'Stop'
$DistDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $DistDir '..\..')).Path
$BaseGguf = "$RepoRoot\model_pipeline\base_weights\Qwen3.8-9B-Distill-f16.gguf"
$BaseGgufDir = Split-Path $BaseGguf -Parent

Write-Host '=== [Paso 0/4] Verificando modelo base F16/BF16 GGUF ===' -ForegroundColor Cyan
if (-not (Test-Path $BaseGguf)) {
    Write-Host 'Descargando pesos base desde Hugging Face (empero-ai/Qwen3.8-9B-Distill)...' -ForegroundColor Yellow
    huggingface-cli download empero-ai/Qwen3.8-9B-Distill-GGUF --local-dir $BaseGgufDir
}

Write-Host '=== [Paso 1/4] Calculando Matriz de Importancia (imatrix) en Español Doméstico ===' -ForegroundColor Cyan
& llama-imatrix -m "$RepoRoot\model_pipeline\base_weights\Qwen3.8-9B-Distill-f16.gguf" -f "$RepoRoot\model_pipeline\corpus\generated\dew_calibration_es.txt" -o "$DistDir\dew_qwen38_es.imatrix" -t 8 -ngl 99 --ctx-size 2048 --chunks 120

Write-Host '=== [Paso 2/4] Generando Edición Compacta 8 GB RAM (IQ3_XXS + embd q4_k / out q5_k) ===' -ForegroundColor Cyan
& llama-quantize --imatrix "$DistDir\dew_qwen38_es.imatrix" --token-embd-type q4_k --output-tensor-type q5_k "$RepoRoot\model_pipeline\base_weights\Qwen3.8-9B-Distill-f16.gguf" "$DistDir\dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf" IQ3_XXS 8

Write-Host '=== [Paso 3/4] Generando Edición Pro 12 GB+ RAM (Q4_K_M + embd q5_k / out q6_k) ===' -ForegroundColor Cyan
& llama-quantize --imatrix "$DistDir\dew_qwen38_es.imatrix" --token-embd-type q5_k --output-tensor-type q6_k "$RepoRoot\model_pipeline\base_weights\Qwen3.8-9B-Distill-f16.gguf" "$DistDir\dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf" Q4_K_M 8

Write-Host '=== [Paso 4/4] Precomputando Prompt Cache del Sistema (TTFT < 0.8s) ===' -ForegroundColor Cyan
& llama-cli -m "$DistDir\dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf" -f "$DistDir\dew_system_prefix.txt" --prompt-cache "$DistDir\dew_system_prompt_8gb.session" --prompt-cache-all -n 1 --ctx-size 4096 -ctk q8_0 -ctv q4_0
& llama-cli -m "$DistDir\dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf" -f "$DistDir\dew_system_prefix.txt" --prompt-cache "$DistDir\dew_system_prompt_12gb.session" --prompt-cache-all -n 1 --ctx-size 4096 -ctk q8_0 -ctv q4_0

Write-Host '=== Empaquetado finalizado con éxito ===' -ForegroundColor Green
