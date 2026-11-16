#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestor de Descarga Resiliente y Verificación Criptográfica de Modelos Locales para Dew.
Diseñado para gestionar la descarga única de:
  - Edición Compacta 8 GB (`dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf`, ~3,75 GB)
  - Edición Pro 12 GB+ (`dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf`, ~5,30 GB)
  - Paquete de voz local (`Whisper Base INT8` + `Piper es_ES`, ~140 MB)

Características esenciales para móvil:
  1. Política Wi-Fi Obligatoria por defecto: bloquea la descarga en datos móviles (4G/5G)
     a menos que el usuario autorice explícitamente usar su tarifa de datos.
  2. Soporte de reanudación HTTP Range (`bytes=<offset>-`): si se corta el Wi-Fi en el 70%,
     continúa desde ese byte exacto sin perder lo descargado.
  3. Verificación de espacio libre previo (+1,2 GB de margen de seguridad) y hash SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

SAFETY_HEADROOM_MB = 1200


@dataclass
class DownloadEligibility:
    can_start: bool
    reason: str
    tier_id: str
    required_mb: int
    free_disk_mb: int
    resume_offset_bytes: int


class DewModelDownloadManager:
    def __init__(self, manifest_path: Path, models_storage_dir: Path) -> None:
        self.manifest_path = manifest_path
        self.models_storage_dir = models_storage_dir
        self.models_storage_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    def get_tier_spec(self, tier_id: str) -> Dict[str, Any]:
        for tier in self.manifest.get("tiers", []):
            if tier["tier_id"] == tier_id:
                return tier
        raise KeyError(f"No existe el perfil de modelo '{tier_id}' en el manifiesto")

    def check_download_eligibility(
        self,
        tier_id: str,
        network_type: str = "wifi",  # 'wifi', 'cellular', 'offline'
        allow_cellular_override: bool = False,
        simulated_free_disk_mb: Optional[int] = None,
    ) -> DownloadEligibility:
        tier = self.get_tier_spec(tier_id)
        voice_mb = sum(
            int(m.get("size_mb", 0)) for m in self.manifest.get("auxiliary_local_models", {}).values()
        )
        required_mb = int(tier["estimated_download_size_mb"]) + voice_mb
        partial_file = self.models_storage_dir / (tier["file_name"] + ".part")
        resume_offset = partial_file.stat().st_size if partial_file.exists() else 0
        remaining_mb = max(0, required_mb - int(resume_offset / (1024 * 1024)))

        if simulated_free_disk_mb is not None:
            free_mb = simulated_free_disk_mb
        else:
            disk_usage = shutil.disk_usage(self.models_storage_dir)
            free_mb = int(disk_usage.free / (1024 * 1024))

        if network_type == "offline":
            return DownloadEligibility(
                can_start=False,
                reason="Sin conexión a internet. Mientras tanto, el inventario y el lector de tickets están operativos offline.",
                tier_id=tier_id,
                required_mb=remaining_mb,
                free_disk_mb=free_mb,
                resume_offset_bytes=resume_offset,
            )

        if network_type == "cellular" and not allow_cellular_override:
            return DownloadEligibility(
                can_start=False,
                reason=(
                    f"Conectado por datos móviles: la descarga inicial de {remaining_mb} MB está pausada "
                    "para proteger tu tarifa de datos. Conéctate a una red Wi-Fi o autoriza el uso de datos."
                ),
                tier_id=tier_id,
                required_mb=remaining_mb,
                free_disk_mb=free_mb,
                resume_offset_bytes=resume_offset,
            )

        if free_mb < (remaining_mb + SAFETY_HEADROOM_MB):
            return DownloadEligibility(
                can_start=False,
                reason=(
                    f"Espacio libre insuficiente: necesitas al menos {remaining_mb + SAFETY_HEADROOM_MB} MB libres "
                    f"(disponibles: {free_mb} MB)."
                ),
                tier_id=tier_id,
                required_mb=remaining_mb,
                free_disk_mb=free_mb,
                resume_offset_bytes=resume_offset,
            )

        return DownloadEligibility(
            can_start=True,
            reason="Listo para descargar en segundo plano con soporte de reanudación HTTP Range.",
            tier_id=tier_id,
            required_mb=remaining_mb,
            free_disk_mb=free_mb,
            resume_offset_bytes=resume_offset,
        )

    @staticmethod
    def build_http_range_headers(resume_offset_bytes: int) -> Dict[str, str]:
        if resume_offset_bytes > 0:
            return {"Range": f"bytes={resume_offset_bytes}-"}
        return {}

    @staticmethod
    def verify_file_sha256(file_path: Path, expected_sha256: str) -> bool:
        h = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower() == expected_sha256.lower()
