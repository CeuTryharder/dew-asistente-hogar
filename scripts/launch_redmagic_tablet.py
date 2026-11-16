#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanzador en Red Local Wi-Fi (LAN) para Tablet Android RedMagic Astra (16 GB RAM).
Arranca el servidor interactivo de Dew en `0.0.0.0:8765` preconfigurado con el perfil
de 16 GB RAM (`Q4_K_M · 8K ctx · Vulkan GPU`) y muestra la dirección IP local de la Wi-Fi
para abrir e instalar la PWA directamente desde Chrome en la tablet RedMagic Astra.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dew_core.hardware_and_orchestrator import HardwareModelSelector, SequentialMemoryManager
from mobile_ui import app_server


def detect_local_wifi_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def main() -> None:
    port = 8765
    lan_ip = detect_local_wifi_ip()

    # Preconfigurar el motor en modo RedMagic Astra 16 GB RAM (Q4_K_M · 8K ctx)
    app_server.APP_STATE.ram_gb = 16.0
    app_server.APP_STATE.dew.tier = HardwareModelSelector.select_tier_for_device(16.0)
    app_server.APP_STATE.dew.memory_mgr = SequentialMemoryManager(
        app_server.APP_STATE.dew.tier.sequential_unload_required
    )

    tablet_url = f"http://{lan_ip}:{port}/?device=redmagic_16gb"

    print("=" * 76)
    print("  DEW · EDICIÓN TABLET REDMAGIC ASTRA (16 GB RAM · Q4_K_M · 8K CTX)")
    print("=" * 76)
    print(f"  1. Conecta tu RedMagic Astra a la misma red Wi-Fi que este PC.")
    print(f"  2. Abre Chrome en la tablet y entra en:")
    print(f"\n       👉  {tablet_url}\n")
    print("  3. En el menú de Chrome (⋮) de tu RedMagic Astra, pulsa:")
    print("       «Añadir a pantalla de inicio» / «Instalar aplicación»")
    print("     para usarla a pantalla completa en formato panorámico de 2 columnas.")
    print("=" * 76)

    app_server.run_server(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
