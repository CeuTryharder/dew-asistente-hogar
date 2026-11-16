#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script Maestro de Calibración (`imatrix`) y Empaquetado Móvil para Dew.
Modelo objetivo: `empero-ai/Qwen3.8-9B-Distill` (Apache 2.0, arquitectura híbrida Qwen3.5-9B).

Funciones principales:
  1. Genera el corpus de calibración en español doméstico (`dew_calibration_es.txt`).
  2. Audita el 100% de las muestras del corpus contra el validador determinista de esquemas y seguridad (`CHEM_GUARD`).
  3. Exporta el prefijo de sistema (`dew_system_prefix.txt`) y las gramáticas GBNF (`dew_fast_turn.gbnf`, `dew_deep_think_turn.gbnf`).
  4. Ejecuta (o genera los scripts listos para ejecutar en GPU/workstation) `llama-imatrix` y `llama-quantize`
     para producir las dos ediciones móviles:
       - Edición 8 GB RAM (`IQ3_XXS` con `--imatrix` + protección de tensores de entrada/salida `q4_k`/`q5_k`).
       - Edición 12 GB+ RAM (`Q4_K_M` con `--imatrix` + tensores `q5_k`/`q6_k`).
  5. Empaqueta el manifiesto de distribución móvil (`dew_mobile_bundle_manifest.json`) con hashes SHA-256
     y parámetros óptimos de `llama.cpp` para Android NDK e iOS Metal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Asegurar que el directorio raíz del proyecto está en sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_pipeline.corpus.generate_calibration_corpus import generate_corpus_files
from model_pipeline.grammars.safety_and_schema_validator import validate_dew_response
from model_pipeline.prompts.dew_prompt_builder import build_qwen38_prompt, get_static_system_prefix

HF_MODEL_ID = "empero-ai/Qwen3.8-9B-Distill"
HF_GGUF_REPO_ID = "empero-ai/Qwen3.8-9B-Distill-GGUF"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_corpus_against_guardrails(jsonl_path: Path) -> Dict[str, Any]:
    """Verifica que todas las muestras del corpus cumplen el esquema JSON y las reglas de seguridad."""
    passed = 0
    failed = 0
    warnings_count = 0
    failure_details: List[str] = []

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            record = json.loads(line)
            res = validate_dew_response(record["assistant_json"])
            if res.is_valid:
                passed += 1
                warnings_count += len(res.warnings)
            else:
                failed += 1
                failure_details.append(f"Muestra #{line_num} ({record.get('category')}): {res.errors}")

    return {
        "passed": passed,
        "failed": failed,
        "warnings_count": warnings_count,
        "failure_details": failure_details,
    }


def build_quantization_commands(
    base_gguf_path: Path,
    corpus_txt_path: Path,
    imatrix_out_path: Path,
    dist_dir: Path,
    threads: int = 8,
    ngl: int = 99,
) -> Dict[str, Any]:
    """
    Construye los comandos exactos de `llama-imatrix`, `llama-quantize` y `llama-cli` (prompt cache).
    Nota de ingeniería crítica:
      En `IQ3_XXS` (para móviles de 8 GB RAM) usamos `--token-embd-type q4_k --output-tensor-type q5_k`.
      Esto mantiene la tabla de vocabulario español y el cabezal de salida en 4/5 bits (~90 MB extra),
      evitando errores ortográficos en castellano o roturas de llaves JSON mientras el cuerpo de 9B
      se comprime a 3 bits guiado por `dew_qwen38_es.imatrix`.
    """
    compact_8gb_out = dist_dir / "dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf"
    pro_12gb_out = dist_dir / "dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf"
    session_cache_8gb = dist_dir / "dew_system_prompt_8gb.session"
    session_cache_12gb = dist_dir / "dew_system_prompt_12gb.session"
    sys_prefix_path = dist_dir / "dew_system_prefix.txt"

    cmd_imatrix = [
        "llama-imatrix",
        "-m", str(base_gguf_path),
        "-f", str(corpus_txt_path),
        "-o", str(imatrix_out_path),
        "-t", str(threads),
        "-ngl", str(ngl),
        "--ctx-size", "2048",
        "--chunks", "120",
    ]

    cmd_quant_8gb = [
        "llama-quantize",
        "--imatrix", str(imatrix_out_path),
        "--token-embd-type", "q4_k",
        "--output-tensor-type", "q5_k",
        str(base_gguf_path),
        str(compact_8gb_out),
        "IQ3_XXS",
        str(threads),
    ]

    cmd_quant_12gb = [
        "llama-quantize",
        "--imatrix", str(imatrix_out_path),
        "--token-embd-type", "q5_k",
        "--output-tensor-type", "q6_k",
        str(base_gguf_path),
        str(pro_12gb_out),
        "Q4_K_M",
        str(threads),
    ]

    cmd_prompt_cache_8gb = [
        "llama-cli",
        "-m", str(compact_8gb_out),
        "-f", str(sys_prefix_path),
        "--prompt-cache", str(session_cache_8gb),
        "--prompt-cache-all",
        "-n", "1",
        "--ctx-size", "4096",
        "-ctk", "q8_0",
        "-ctv", "q4_0",
    ]

    cmd_prompt_cache_12gb = [
        "llama-cli",
        "-m", str(pro_12gb_out),
        "-f", str(sys_prefix_path),
        "--prompt-cache", str(session_cache_12gb),
        "--prompt-cache-all",
        "-n", "1",
        "--ctx-size", "4096",
        "-ctk", "q8_0",
        "-ctv", "q4_0",
    ]

    return {
        "paths": {
            "base_gguf": str(base_gguf_path),
            "imatrix": str(imatrix_out_path),
            "compact_8gb_gguf": str(compact_8gb_out),
            "pro_12gb_gguf": str(pro_12gb_out),
            "session_cache_8gb": str(session_cache_8gb),
            "session_cache_12gb": str(session_cache_12gb),
            "system_prefix_txt": str(sys_prefix_path),
        },
        "commands": {
            "1_compute_imatrix": cmd_imatrix,
            "2_quantize_8gb_compact": cmd_quant_8gb,
            "3_quantize_12gb_pro": cmd_quant_12gb,
            "4_precompute_prompt_cache_8gb": cmd_prompt_cache_8gb,
            "5_precompute_prompt_cache_12gb": cmd_prompt_cache_12gb,
        },
    }


def write_runner_scripts(dist_dir: Path, cmd_bundle: Dict[str, Any]) -> Dict[str, str]:
    """
    Genera scripts ejecutables y portables en PowerShell (`run_quantization.ps1`) y
    Bash (`run_quantization.sh`) usando rutas relativas al repositorio (sin rutas de usuario).
    """
    cmds = cmd_bundle["commands"]
    paths = cmd_bundle["paths"]
    resolved_dist = dist_dir.resolve()
    resolved_root = PROJECT_ROOT.resolve()

    def _to_ps_arg(token: str) -> str:
        p = Path(token)
        if p.is_absolute():
            rp = p.resolve()
            try:
                rel_dist = rp.relative_to(resolved_dist)
                win_rel = str(rel_dist).replace("/", "\\")
                return f'"$DistDir\\{win_rel}"' if win_rel != "." else '"$DistDir"'
            except ValueError:
                pass
            try:
                rel_root = rp.relative_to(resolved_root)
                win_rel = str(rel_root).replace("/", "\\")
                return f'"$RepoRoot\\{win_rel}"'
            except ValueError:
                pass
        return f"'{token}'" if " " in token else token

    def _to_sh_arg(token: str) -> str:
        p = Path(token)
        if p.is_absolute():
            rp = p.resolve()
            try:
                rel_dist = rp.relative_to(resolved_dist)
                posix_rel = rel_dist.as_posix()
                return f'"${{DIST_DIR}}/{posix_rel}"' if posix_rel != "." else '"${DIST_DIR}"'
            except ValueError:
                pass
            try:
                rel_root = rp.relative_to(resolved_root)
                return f'"${{REPO_ROOT}}/{rel_root.as_posix()}"'
            except ValueError:
                pass
        return f'"{token}"' if " " in token else token

    base_ps = _to_ps_arg(paths["base_gguf"])
    base_sh = _to_sh_arg(paths["base_gguf"])

    ps1_lines = [
        "# Script Automático de Calibración y Cuantización para Dew (PowerShell)",
        "# Modelo base: empero-ai/Qwen3.8-9B-Distill (Apache 2.0)",
        "$ErrorActionPreference = 'Stop'",
        "$DistDir = $PSScriptRoot",
        "$RepoRoot = (Resolve-Path (Join-Path $DistDir '..\\..')).Path",
        f"$BaseGguf = {base_ps}",
        "$BaseGgufDir = Split-Path $BaseGguf -Parent",
        "",
        "Write-Host '=== [Paso 0/4] Verificando modelo base F16/BF16 GGUF ===' -ForegroundColor Cyan",
        "if (-not (Test-Path $BaseGguf)) {",
        f"    Write-Host 'Descargando pesos base desde Hugging Face ({HF_MODEL_ID})...' -ForegroundColor Yellow",
        f"    huggingface-cli download {HF_GGUF_REPO_ID} --local-dir $BaseGgufDir",
        "}",
        "",
        "Write-Host '=== [Paso 1/4] Calculando Matriz de Importancia (imatrix) en Español Doméstico ===' -ForegroundColor Cyan",
        "& " + " ".join(_to_ps_arg(c) for c in cmds["1_compute_imatrix"]),
        "",
        "Write-Host '=== [Paso 2/4] Generando Edición Compacta 8 GB RAM (IQ3_XXS + embd q4_k / out q5_k) ===' -ForegroundColor Cyan",
        "& " + " ".join(_to_ps_arg(c) for c in cmds["2_quantize_8gb_compact"]),
        "",
        "Write-Host '=== [Paso 3/4] Generando Edición Pro 12 GB+ RAM (Q4_K_M + embd q5_k / out q6_k) ===' -ForegroundColor Cyan",
        "& " + " ".join(_to_ps_arg(c) for c in cmds["3_quantize_12gb_pro"]),
        "",
        "Write-Host '=== [Paso 4/4] Precomputando Prompt Cache del Sistema (TTFT < 0.8s) ===' -ForegroundColor Cyan",
        "& " + " ".join(_to_ps_arg(c) for c in cmds["4_precompute_prompt_cache_8gb"]),
        "& " + " ".join(_to_ps_arg(c) for c in cmds["5_precompute_prompt_cache_12gb"]),
        "",
        "Write-Host '=== Empaquetado finalizado con éxito ===' -ForegroundColor Green",
    ]

    sh_lines = [
        "#!/usr/bin/env bash",
        "# Script Automático de Calibración y Cuantización para Dew (Bash)",
        "set -euo pipefail",
        'DIST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'REPO_ROOT="$(cd "${DIST_DIR}/../.." && pwd)"',
        f"BASE_GGUF={base_sh}",
        "",
        'if [ ! -f "${BASE_GGUF}" ]; then',
        f'  echo "Descargando modelo base desde Hugging Face ({HF_GGUF_REPO_ID})..."',
        f'  huggingface-cli download {HF_GGUF_REPO_ID} --local-dir "$(dirname "${{BASE_GGUF}}")"',
        "fi",
        "",
        'echo "=== [1/4] Calculando imatrix en español doméstico ==="',
        " ".join(_to_sh_arg(c) for c in cmds["1_compute_imatrix"]),
        "",
        'echo "=== [2/4] Cuantizando Edición Compacta 8 GB RAM (IQ3_XXS) ==="',
        " ".join(_to_sh_arg(c) for c in cmds["2_quantize_8gb_compact"]),
        "",
        'echo "=== [3/4] Cuantizando Edición Pro 12 GB+ RAM (Q4_K_M) ==="',
        " ".join(_to_sh_arg(c) for c in cmds["3_quantize_12gb_pro"]),
        "",
        'echo "=== [4/4] Precomputando sesiones de Prompt Cache ==="',
        " ".join(_to_sh_arg(c) for c in cmds["4_precompute_prompt_cache_8gb"]),
        " ".join(_to_sh_arg(c) for c in cmds["5_precompute_prompt_cache_12gb"]),
        "",
        'echo "=== Empaquetado finalizado con éxito ==="',
    ]

    ps1_path = dist_dir / "run_quantization.ps1"
    sh_path = dist_dir / "run_quantization.sh"
    ps1_path.write_text("\n".join(ps1_lines) + "\n", encoding="utf-8")
    sh_path.write_text("\n".join(sh_lines) + "\n", encoding="utf-8")

    return {"powershell_script": str(ps1_path), "bash_script": str(sh_path)}


def generate_mobile_manifest(
    dist_dir: Path,
    grammar_fast_path: Path,
    grammar_deep_path: Path,
    schema_path: Path,
    sys_prefix_path: Path,
    corpus_stats: Dict[str, Any],
) -> Path:
    """
    Genera el archivo `dew_mobile_bundle_manifest.json` que consume la aplicación móvil
    (Android / iOS) para seleccionar y descargar el paquete adecuado según su RAM física.
    """
    manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "product": "Dew - Asistente Doméstico Personal Local-First",
        "base_model": {
            "huggingface_id": HF_MODEL_ID,
            "architecture": "Qwen3.5-9B Hybrid (Gated DeltaNet + Full Attention)",
            "license": "Apache-2.0",
            "supports_thinking_switch": True,
            "fast_turn_prefill": "<|im_start|>assistant\n<think>\n</think>\n",
            "deep_think_prefill": "<|im_start|>assistant\n<think>\n",
        },
        "calibration_metadata": {
            "language": "es-ES",
            "domain": "Hogar, Alimentación, Limpieza, Domótica y Servicios Digitales en España",
            "total_samples": corpus_stats["total_samples"],
            "approx_calibration_tokens": corpus_stats["approx_tokens"],
        },
        "tiers": [
            {
                "tier_id": "DEW_9B_COMPACT_8GB",
                "display_name": "Dew 9B Edición Compacta (Móviles 8 GB RAM)",
                "target_ram_gb_min": 7.5,
                "target_ram_gb_max": 11.4,
                "quantization": {
                    "body_type": "IQ3_XXS",
                    "bits_per_weight_avg": 3.06,
                    "token_embd_type": "q4_k",
                    "output_tensor_type": "q5_k",
                    "uses_spanish_imatrix": True,
                },
                "file_name": "dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf",
                "estimated_download_size_mb": 3840,
                "estimated_runtime_ram_mb": 4350,
                "llama_cpp_runtime_config": {
                    "n_ctx": 4096,
                    "type_k": "q8_0",
                    "type_v": "q4_0",
                    "flash_attn": True,
                    "use_mmap": True,
                    "use_mlock": False,
                    "n_batch": 512,
                    "n_ubatch": 256,
                    "sequential_unload_vision_and_stt": True,
                },
            },
            {
                "tier_id": "DEW_9B_PRO_12GB",
                "display_name": "Dew 9B Edición Pro (Móviles 12 GB+ RAM)",
                "target_ram_gb_min": 11.5,
                "target_ram_gb_max": 64.0,
                "quantization": {
                    "body_type": "Q4_K_M",
                    "bits_per_weight_avg": 4.85,
                    "token_embd_type": "q5_k",
                    "output_tensor_type": "q6_k",
                    "uses_spanish_imatrix": True,
                },
                "file_name": "dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf",
                "estimated_download_size_mb": 5420,
                "estimated_runtime_ram_mb": 6100,
                "llama_cpp_runtime_config": {
                    "n_ctx": 4096,
                    "type_k": "q8_0",
                    "type_v": "q4_0",
                    "flash_attn": True,
                    "use_mmap": True,
                    "use_mlock": False,
                    "n_batch": 512,
                    "n_ubatch": 512,
                    "sequential_unload_vision_and_stt": False,
                },
            },
        ],
        "auxiliary_local_models": {
            "vad": {
                "name": "Silero VAD v5",
                "runtime": "sherpa-onnx",
                "license": "MIT",
                "size_mb": 1.8,
            },
            "stt": {
                "name": "Whisper Base Multilingual INT8",
                "runtime": "sherpa-onnx",
                "license": "MIT",
                "size_mb": 78.0,
                "language": "es",
            },
            "tts": {
                "name": "Piper VITS es_ES (davefx-medium)",
                "runtime": "sherpa-onnx",
                "license": "MIT",
                "size_mb": 61.5,
                "language": "es-ES",
            },
        },
        "bundled_control_artifacts": {
            "fast_turn_grammar": {
                "file": grammar_fast_path.name,
                "sha256": sha256_file(grammar_fast_path),
            },
            "deep_think_grammar": {
                "file": grammar_deep_path.name,
                "sha256": sha256_file(grammar_deep_path),
            },
            "json_schema": {
                "file": schema_path.name,
                "sha256": sha256_file(schema_path),
            },
            "system_prefix": {
                "file": sys_prefix_path.name,
                "sha256": sha256_file(sys_prefix_path),
            },
        },
    }

    manifest_path = dist_dir / "dew_mobile_bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def run_self_tests() -> Dict[str, Any]:
    """
    Ejecuta pruebas unitarias integradas sobre:
      - El clasificador de modo `<think>` vs `<think>\\n</think>`.
      - El guardarraíl químico (`CHEM_GUARD`) ante mezclas peligrosas (lejía + amoniaco/vinagre).
      - El guardarraíl de rango de temperatura domótica (16–26 ºC) y dispositivos críticos.
    """
    # 1. Prueba de enrutamiento de prompt rápido vs pensamiento profundo
    fast_prompt = build_qwen38_prompt(
        "Apaga la luz de la cocina y apunta que falta leche",
        "Cocina encendida. Leche baja.",
    )
    assert fast_prompt.mode == "fast", "Debería elegir modo fast"
    assert fast_prompt.full_prompt.endswith("<|im_start|>assistant\n<think>\n</think>\n")

    plan_prompt = build_qwen38_prompt(
        "Planifícame el menú semanal de cenas con presupuesto de 30 euros aprovechando lo que caduca",
        "Queso fresco caduca mañana.",
    )
    assert plan_prompt.mode == "deep_think", "Debería elegir modo deep_think"
    assert plan_prompt.full_prompt.endswith("<|im_start|>assistant\n<think>\n")

    # 2. Prueba de bloqueo de mezcla química peligrosa (CHEM_GUARD)
    bad_chemical_output = {
        "spoken_reply": "Para desinfectar a fondo mezcla un vaso de lejía con un chorro de amoniaco en el cubo.",
        "thinking_mode_used": False,
        "uncertainty_notes": [],
        "proposed_actions": [],
    }
    chem_res = validate_dew_response(bad_chemical_output)
    assert not chem_res.is_valid, "CHEM_GUARD debía bloquear la mezcla de lejía + amoniaco"

    # 3. Prueba de bloqueo de temperatura domótica peligrosa
    bad_temp_output = {
        "spoken_reply": "Pongo la calefacción a 34 grados.",
        "thinking_mode_used": False,
        "uncertainty_notes": [],
        "proposed_actions": [
            {
                "tool": "control_home_device",
                "requires_confirmation": False,
                "payload": {"domain": "climate", "target_celsius": 34.0},
            }
        ],
    }
    temp_res = validate_dew_response(bad_temp_output)
    assert not temp_res.is_valid, "Debía bloquear temperatura > 26.0 ºC"

    return {
        "prompt_switch_test": "OK (<think>\\n</think> en voz rápida y <think> abierto en planificación)",
        "chem_guard_test": "OK (Bloqueada mezcla peligrosa de lejía + amoniaco)",
        "domotics_safety_test": "OK (Bloqueada consigna térmica fuera de 16-26 ºC)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline de Calibración (imatrix) y Empaquetado Móvil para Dew (Qwen3.8-9B-Distill)"
    )
    parser.add_argument(
        "--base-gguf",
        type=Path,
        default=PROJECT_ROOT / "model_pipeline" / "base_weights" / "Qwen3.8-9B-Distill-f16.gguf",
        help="Ruta al archivo GGUF maestro (F16/BF16/Q8_0) de empero-ai/Qwen3.8-9B-Distill",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=PROJECT_ROOT / "model_pipeline" / "dist",
        help="Directorio de salida para artefactos empaquetados y manifiesto móvil",
    )
    parser.add_argument("--threads", type=int, default=8, help="Número de hilos de CPU para llama-quantize")
    parser.add_argument("--ngl", type=int, default=99, help="Capas en GPU para llama-imatrix")
    parser.add_argument(
        "--execute-quantize",
        action="store_true",
        help="Ejecuta realmente llama-imatrix y llama-quantize si los binarios y el GGUF base están presentes",
    )
    args = parser.parse_args()

    dist_dir: Path = args.dist_dir.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir = PROJECT_ROOT / "model_pipeline" / "corpus" / "generated"
    grammars_dir = PROJECT_ROOT / "model_pipeline" / "grammars"

    print("1. Generando corpus de calibración en español doméstico para empero-ai/Qwen3.8-9B-Distill...")
    corpus_stats = generate_corpus_files(corpus_dir)

    print("2. Verificando el 100% del corpus contra el validador determinista y CHEM_GUARD...")
    validation_report = verify_corpus_against_guardrails(Path(corpus_stats["jsonl_path"]))
    if validation_report["failed"] > 0:
        print("ERROR: Fallos de validación en el corpus:", validation_report["failure_details"], file=sys.stderr)
        return 1

    print("3. Ejecutando batería de autodiagnóstico (Switch <think>, CHEM_GUARD, Domótica)...")
    self_test_report = run_self_tests()

    print("4. Exportando artefactos de control (Prefijo de sistema KV, Gramáticas GBNF y Esquema JSON)...")
    sys_prefix_path = dist_dir / "dew_system_prefix.txt"
    sys_prefix_path.write_text(get_static_system_prefix(), encoding="utf-8")

    grammar_fast_dst = dist_dir / "dew_fast_turn.gbnf"
    grammar_deep_dst = dist_dir / "dew_deep_think_turn.gbnf"
    schema_dst = dist_dir / "dew_tool_schema.json"
    shutil.copy2(grammars_dir / "dew_fast_turn.gbnf", grammar_fast_dst)
    shutil.copy2(grammars_dir / "dew_deep_think_turn.gbnf", grammar_deep_dst)
    shutil.copy2(grammars_dir / "dew_tool_schema.json", schema_dst)

    imatrix_out_path = dist_dir / "dew_qwen38_es.imatrix"
    cmd_bundle = build_quantization_commands(
        base_gguf_path=args.base_gguf.resolve(),
        corpus_txt_path=Path(corpus_stats["txt_path"]),
        imatrix_out_path=imatrix_out_path,
        dist_dir=dist_dir,
        threads=args.threads,
        ngl=args.ngl,
    )

    print("5. Generando scripts de cuantización (PowerShell y Bash) y manifiesto móvil...")
    runner_scripts = write_runner_scripts(dist_dir, cmd_bundle)
    manifest_path = generate_mobile_manifest(
        dist_dir=dist_dir,
        grammar_fast_path=grammar_fast_dst,
        grammar_deep_path=grammar_deep_dst,
        schema_path=schema_dst,
        sys_prefix_path=sys_prefix_path,
        corpus_stats=corpus_stats,
    )

    if args.execute_quantize:
        llama_imatrix_bin = shutil.which("llama-imatrix")
        llama_quantize_bin = shutil.which("llama-quantize")
        if not llama_imatrix_bin or not llama_quantize_bin:
            print(
                "AVISO: No se encontraron 'llama-imatrix' o 'llama-quantize' en el PATH. "
                "Se han dejado listos los scripts en dist/ para ejecutarlos cuando instales llama.cpp.",
                file=sys.stderr,
            )
        elif not args.base_gguf.exists():
            print(
                f"AVISO: No se encontró el archivo base '{args.base_gguf}'. "
                f"Ejecuta '{runner_scripts['powershell_script']}' para descargarlo y cuantizarlo.",
                file=sys.stderr,
            )
        else:
            for step_name, cmd in cmd_bundle["commands"].items():
                print(f"Ejecutando {step_name}: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)

    summary = {
        "status": "READY",
        "corpus": corpus_stats,
        "corpus_validation": validation_report,
        "self_tests": self_test_report,
        "manifest_path": str(manifest_path),
        "runner_scripts": runner_scripts,
    }
    print("\n=== RESUMEN DEL PIPELINE DE CALIBRACIÓN Y EMPAQUETADO ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
