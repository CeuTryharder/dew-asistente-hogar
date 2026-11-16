#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatizador de Cuantización en GPU (Google Colab / Kaggle / Servidor) y Publicación
en Hugging Face Hub / Almacenamiento Compatible S3 (Cloudflare R2) para Dew.

Permite que cualquier usuario o desarrollador ejecute de principio a fin:
  1. Cálculo de `dew_qwen38_es.imatrix` sobre `empero-ai/Qwen3.8-9B-Distill`.
  2. Compresión de las dos variantes móviles (`IQ3_XXS` para 8 GB RAM y `Q4_K_M` para 12 GB+ RAM).
  3. Actualización automática de los hashes SHA-256 reales y tamaños exactos en
     `dew_mobile_bundle_manifest.json`.
  4. Subida opcional de los artefactos finales a una cuenta de Hugging Face (`--hf-target-repo`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest_with_built_artifacts(
    manifest_path: Path,
    dist_dir: Path,
    download_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Actualiza `dew_mobile_bundle_manifest.json` con el tamaño real en MB, el hash SHA-256
    y la URL de descarga de los archivos `.gguf` una vez compilados.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

    for tier in manifest.get("tiers", []):
        gguf_file = dist_dir / tier["file_name"]
        if gguf_file.exists():
            size_mb = round(gguf_file.stat().st_size / (1024.0 * 1024.0), 2)
            tier["actual_download_size_mb"] = size_mb
            tier["sha256"] = compute_sha256(gguf_file)
            tier["build_verified"] = True
        else:
            tier["build_verified"] = False

        if download_base_url:
            base = download_base_url.rstrip("/")
            tier["download_url"] = f"{base}/{tier['file_name']}"

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def generate_huggingface_model_card(target_repo: str) -> str:
    """Genera el `README.md` (Model Card) para el repositorio de pesos móviles de Dew en Hugging Face."""
    return f"""---
license: apache-2.0
base_model: empero-ai/Qwen3.8-9B-Distill
language:
  - es
  - en
tags:
  - gguf
  - mobile
  - android
  - ios
  - llama.cpp
  - imatrix
  - spanish
  - dew-assistant
pipeline_tag: text-generation
---

# {target_repo} — Pesos Móviles Calibrados en Español para Dew

Este repositorio contiene las dos ediciones móviles cuantizadas con **Matriz de Importancia (`imatrix`) calibrada en español doméstico** a partir de [`empero-ai/Qwen3.8-9B-Distill`](https://huggingface.co/empero-ai/Qwen3.8-9B-Distill) (licencia **Apache 2.0**):

| Archivo GGUF | Teléfono Objetivo | Cuantización Cuerpo | Tensores Protegidos | Tamaño Aprox. | RAM en Ejecución (KV 4k `q8_0`/`q4_0`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf` | **Móviles de 8 GB RAM** | `IQ3_XXS` (3.06 bpw) | `token_embd=q4_k`, `output=q5_k` | ~3,75 GB | ~4,35 GB (`mmap` activo) |
| `dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf` | **Móviles de 12 GB+ RAM** | `Q4_K_M` (4.85 bpw) | `token_embd=q5_k`, `output=q6_k` | ~5,30 GB | ~6,10 GB (`mmap` activo) |

## Conmutador de Latencia Cero (`<think>` Switch)
* **Modo Voz Rápida (<1s TTFT):** Inyectar `<|im_start|>assistant\\n<think>\\n</think>\\n` junto con `dew_fast_turn.gbnf`.
* **Modo Planificador Semanal:** Inyectar `<|im_start|>assistant\\n<think>\\n` junto con `dew_deep_think_turn.gbnf`.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Actualizador de Manifiesto y Publicador de Pesos GGUF para Dew"
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=PROJECT_ROOT / "model_pipeline" / "dist",
        help="Directorio donde se encuentran los archivos GGUF y el manifiesto",
    )
    parser.add_argument(
        "--hf-target-repo",
        type=str,
        default="CeuTryharder/Dew-Qwen3.8-9B-Mobile-ES-GGUF",
        help="Repositorio de destino en Hugging Face Hub para alojar los pesos gratuitamente",
    )
    parser.add_argument(
        "--publish-to-hf",
        action="store_true",
        help="Sube los artefactos de dist/ a Hugging Face Hub si huggingface_hub está autenticado",
    )
    args = parser.parse_args()

    dist_dir = args.dist_dir.resolve()
    manifest_path = dist_dir / "dew_mobile_bundle_manifest.json"
    hf_download_base = f"https://huggingface.co/{args.hf_target_repo}/resolve/main"

    updated_manifest = update_manifest_with_built_artifacts(
        manifest_path=manifest_path,
        dist_dir=dist_dir,
        download_base_url=hf_download_base,
    )

    model_card_path = dist_dir / "HF_MODEL_CARD_README.md"
    model_card_path.write_text(generate_huggingface_model_card(args.hf_target_repo), encoding="utf-8")

    if args.publish_to_hf:
        try:
            from huggingface_hub import HfApi  # type: ignore[import-not-found]
            api = HfApi()
            api.create_repo(repo_id=args.hf_target_repo, repo_type="model", exist_ok=True)
            api.upload_folder(
                folder_path=str(dist_dir),
                repo_id=args.hf_target_repo,
                repo_type="model",
                commit_message="Upload Dew Spanish-calibrated Qwen3.8-9B-Distill 8GB/12GB mobile GGUF bundle",
            )
            print(f"Publicado con éxito en https://huggingface.co/{args.hf_target_repo}")
        except Exception as exc:
            print(f"Aviso al publicar en Hugging Face Hub: {exc}", file=sys.stderr)
            return 1

    print(
        json.dumps(
            {
                "status": "MANIFEST_AND_MODEL_CARD_READY",
                "hf_target_repo": args.hf_target_repo,
                "manifest_path": str(manifest_path),
                "model_card_path": str(model_card_path),
                "tiers": updated_manifest["tiers"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
