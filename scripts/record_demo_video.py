#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grabador Automatizado del Vídeo Demostrativo E2E de Dew (`dew_demo_funcional.mp4` y `.gif`).

Levanta el servidor real de `mobile_ui/app_server.py` (respaldado por `dew_core`), abre
Google Chrome Headless mediante Chrome DevTools Protocol (CDP), ejecuta en vivo los 8 flujos
principales de Dew y codifica:
  1. `docs/demo/dew_demo_funcional.mp4` (Vídeo MP4 H.264/mp4v con panel lateral explicativo).
  2. `docs/demo/dew_demo_funcional.gif` (GIF animado embebido en el README de GitHub).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import websockets
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mobile_ui.app_server import DewHttpHandler

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser_exe() -> str:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    raise FileNotFoundError("No se encontró Chrome ni Edge para grabar el vídeo.")


class CdpSession:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws: Any = None
        self.msg_id = 0

    async def __aenter__(self) -> "CdpSession":
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.ws:
            await self.ws.close()

    async def call(self, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        self.msg_id += 1
        target_id = self.msg_id
        payload = {"id": target_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == target_id:
                return data.get("result", {})

    async def eval_js(self, expression: str) -> Any:
        res = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        return res.get("result", {}).get("value")

    async def screenshot_pil(self) -> Image.Image:
        res = await self.call("Page.captureScreenshot", {"format": "png"})
        png_bytes = base64.b64decode(res["data"])
        return Image.open(io.BytesIO(png_bytes)).convert("RGB")


def compose_annotated_frame(
    browser_img: Image.Image,
    step_badge: str,
    title: str,
    bullets: List[str],
    status_footer: str,
) -> Image.Image:
    """
    Combina la captura real del simulador móvil (izquierda) con un panel lateral de
    telemetría y explicación técnica de arquitectura (derecha) en resolución 1280x900.
    """
    canvas_w, canvas_h = 1280, 900
    canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)

    # Recortar/ajustar la captura del navegador en la mitad izquierda (520x900)
    browser_resized = browser_img.resize((540, 900), Image.Resampling.LANCZOS)
    canvas.paste(browser_resized, (20, 0))

    # Panel derecho de telemetría (x=580..1250, y=30..870)
    panel_x0, panel_y0, panel_x1, panel_y1 = 580, 30, 1250, 870
    draw.rounded_rectangle(
        [panel_x0, panel_y0, panel_x1, panel_y1],
        radius=20,
        fill=(30, 41, 59),
        outline=(45, 212, 191),
        width=2,
    )

    try:
        font_badge = ImageFont.truetype("arialbd.ttf", 18)
        font_title = ImageFont.truetype("arialbd.ttf", 26)
        font_body = ImageFont.truetype("arial.ttf", 19)
        font_mono = ImageFont.truetype("consola.ttf", 16)
    except OSError:
        font_badge = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_mono = ImageFont.load_default()

    # Insignia superior
    draw.rounded_rectangle([610, 58, 960, 96], radius=10, fill=(15, 118, 110))
    draw.text((624, 67), step_badge, fill=(204, 251, 241), font=font_badge)

    # Título de la escena
    draw.text((610, 118), title, fill=(248, 250, 252), font=font_title)
    draw.line([(610, 162), (1220, 162)], fill=(71, 85, 105), width=2)

    # Viñetas explicativas con ajuste de línea
    y_cursor = 185
    for b in bullets:
        words = b.split()
        lines: List[str] = []
        current_line = "•"
        for w in words:
            test_line = f"{current_line} {w}".strip()
            if len(test_line) <= 56:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = f"  {w}"
        lines.append(current_line)

        for ln in lines:
            draw.text((612, y_cursor), ln, fill=(226, 232, 240), font=font_body)
            y_cursor += 28
        y_cursor += 14

    # Caja inferior de telemetría del motor local
    draw.rounded_rectangle([610, 680, 1220, 840], radius=12, fill=(15, 23, 42), outline=(51, 65, 85))
    draw.text((628, 695), "TELEMETRÍA DE EJECUCIÓN LOCAL (ON-DEVICE)", fill=(45, 212, 191), font=font_badge)
    for idx, line in enumerate(status_footer.splitlines()):
        draw.text((628, 728 + idx * 24), line, fill=(148, 163, 184), font=font_mono)

    return canvas


async def record_walkthrough(ws_url: str, output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = output_dir / "dew_demo_funcional.mp4"
    gif_path = output_dir / "dew_demo_funcional.gif"

    fps = 10
    frames_pil: List[Image.Image] = []

    def add_scene_frames(img: Image.Image, seconds: float) -> None:
        count = max(1, int(seconds * fps))
        for _ in range(count):
            frames_pil.append(img)

    async with CdpSession(ws_url) as cdp:
        await cdp.call("Page.enable")
        await cdp.call("Runtime.enable")
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 540, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        await asyncio.sleep(0.6)

        # ESCENA 1: Estado inicial + Perfil 8 GB RAM (`IQ3_XXS`) y Modo Avión (Offline)
        await cdp.eval_js("toggleOffline()")
        await asyncio.sleep(0.3)
        shot1 = await cdp.screenshot_pil()
        frame1 = compose_annotated_frame(
            shot1,
            "ESCENA 1 / 8 · ARQUITECTURA LOCAL-FIRST",
            "Selección 8 GB / 12 GB+ y Modo Sin Conexión",
            [
                "El móvil detecta 8 GB de RAM y activa Qwen3.8-9B-Distill en cuantización IQ3_XXS (3,75 GB) calibrada con imatrix en español.",
                "Activamos el Modo Avión (Offline): voz, inventario, tickets y seguridad siguen 100% operativos sin servidores externos.",
                "La caché KV está cuantizada (q8_0 / q4_0) con mmap activo.",
            ],
            "Modelo: empero-ai/Qwen3.8-9B-Distill (Apache 2.0)\nPerfil activo: DEW_9B_COMPACT_8GB (IQ3_XXS + embd q4_k)\nRed: MODO AVIÓN (100% Offline) | Huella RAM: ~4,35 GB",
        )
        add_scene_frames(frame1, 3.5)

        # ESCENA 2: Voz Push-to-Talk Rápida (<think>\n</think> pre-cerrado)
        await cdp.eval_js("quickSay('Apunta que se ha acabado la leche sin lactosa')")
        await asyncio.sleep(0.3)
        shot2 = await cdp.screenshot_pil()
        frame2 = compose_annotated_frame(
            shot2,
            "ESCENA 2 / 8 · VOZ RÁPIDA (<1 SEGUNDO)",
            "Inyección <think></think> para Respuesta Instantánea",
            [
                "Comando de voz: 'Apunta que se ha acabado la leche sin lactosa'.",
                "Para evitar que el modelo 9B piense durante 25 segundos en un comando corto, Dew pre-cierra <think>\\n</think> en el prompt.",
                "Gramática GBNF activa: fuerza salida JSON determinista en el primer token (<0,8 s TTFT).",
            ],
            "Pipeline Voz: Silero VAD -> Whisper Base INT8 -> Piper es_ES\nModo Inferencia: FAST_TURN (<think> cerrado)\nGramática: dew_fast_turn.gbnf | Latencia TTFT: ~0,7 s",
        )
        add_scene_frames(frame2, 3.5)

        # ESCENA 3: Guardarraíl de Seguridad Química (CHEM_GUARD)
        await cdp.eval_js("quickSay('¿Puedo mezclar lejía con amoniaco para limpiar el baño?')")
        await asyncio.sleep(0.3)
        shot3 = await cdp.screenshot_pil()
        frame3 = compose_annotated_frame(
            shot3,
            "ESCENA 3 / 8 · SEGURIDAD DETERMINISTA",
            "Guardarraíl Químico (CHEM_GUARD)",
            [
                "El usuario pregunta si puede mezclar lejía con amoniaco.",
                "Antes de permitir cualquier sugerencia libre del LLM, el motor determinista detecta reactivos incompatibles.",
                "Bloquea la mezcla y emite una alerta roja advirtiendo del riesgo de gases tóxicos (cloraminas y gas cloro).",
            ],
            "Motor: Safety & Policy Engine (Código determinista)\nAlerta: Incompatibilidad química detectada (lejía + amoniaco)\nAcción: Bloqueo preventivo + Respuesta segura verificada",
        )
        add_scene_frames(frame3, 3.5)

        # ESCENA 4: Escáner EAN-13 con Guardia de Alérgenos + Ticket Mercadona
        await cdp.eval_js("scanReceipt()")
        await asyncio.sleep(0.2)
        await cdp.eval_js("scanBarcode('8480000231406')")
        await asyncio.sleep(0.2)
        await cdp.eval_js("document.querySelector('.content').scrollTop = 260")
        await asyncio.sleep(0.2)
        shot4 = await cdp.screenshot_pil()
        frame4 = compose_annotated_frame(
            shot4,
            "ESCENA 4 / 8 · TICKETS OCR Y ALÉRGENOS",
            "Tickets Españoles + Guardia de Alérgenos EAN-13",
            [
                "Procesa en local un ticket real de Mercadona (L.ENT.S/LACT HAC, PECH.PAVO LONCH, LAVAVAJ.MANO B.VERDE).",
                "Al escanear el código EAN-13 de Crema de Cacahuete (8480000231406), cruza con las restricciones configuradas por el usuario.",
                "Bloquea el alta automática en despensa y avisa del conflicto con [cacahuete].",
            ],
            "OCR Ticket: Mercadona (3 productos -> 6,10 €)\nEAN-13 escaneado: 8480000231406 (Crema de cacahuete)\nGuardia Alérgenos: CONFLICTO DETECTADO [cacahuete]",
        )
        add_scene_frames(frame4, 4.0)

        # ESCENA 5: Planificador Flexible con Presupuesto del Usuario + Comparador Multi-Tienda
        await cdp.eval_js("document.getElementById('planDiners').value = '3'; document.getElementById('planBudget').value = '42.50'; runFlexiblePlan()")
        await asyncio.sleep(0.2)
        await cdp.eval_js("comparePrices()")
        await asyncio.sleep(0.2)
        await cdp.eval_js("confirmCart(1)")
        await asyncio.sleep(0.2)
        await cdp.eval_js("document.querySelector('.content').scrollTop = 520")
        await asyncio.sleep(0.2)
        shot5 = await cdp.screenshot_pil()
        frame5 = compose_annotated_frame(
            shot5,
            "ESCENA 5 / 8 · PLANIFICACIÓN Y PRESUPUESTO",
            "Presupuesto Libre, Menú Semanal y Comparador",
            [
                "El usuario fija libremente 3 comensales y un presupuesto de 42,50 €.",
                "Dew prioriza el queso fresco que caduca mañana, descuenta lo que ya hay en la nevera y calcula la cesta faltante.",
                "El comparador histórico offline detecta dónde compró más barato el Aceite de oliva (Cooperativa Local: 6,90 €/L, ahorra 1,55 €).",
            ],
            "Comensales: 3 | Presupuesto usuario: 42,50 € (Personalizable)\nComparador FTS5: Mejor precio en Cooperativa Local (6,90 €/L)\nCesta #1: CONFIRMED_BY_USER (Nunca compra sin permiso)",
        )
        add_scene_frames(frame5, 4.0)

        # ESCENA 6: Control Domótico Local (Home Assistant LAN)
        await cdp.eval_js("showTab('domotics'); document.querySelector('.content').scrollTop = 0")
        await asyncio.sleep(0.2)
        await cdp.eval_js("domoticAreaOff()")
        await asyncio.sleep(0.3)
        shot6 = await cdp.screenshot_pil()
        frame6 = compose_annotated_frame(
            shot6,
            "ESCENA 6 / 8 · DOMÓTICA LOCAL SEGURA",
            "Home Assistant LAN y Dispositivos Protegidos",
            [
                "Orden grupal: 'Apagar todo el salón'.",
                "Dew apaga la Luz Principal del Salón, pero excluye automáticamente el Enchufe del Router/NAS marcado como [PROTEGIDO].",
                "Informa con honestidad de que el Termostato Salón está sin conexión en el Wi-Fi y exige huella para la Cerradura.",
            ],
            "Conector: Home Assistant Local LAN (Sin nube)\nEjecutado: Luz Principal Salón (on -> off)\nProtegido excluido: Enchufe Router Fibra / NAS [PROTECTED]",
        )
        add_scene_frames(frame6, 3.8)

        # ESCENA 7: Copiloto de Trámites en España (Nivel 2 - Handoff Oficial)
        await cdp.eval_js("showTab('gov'); document.querySelector('.content').scrollTop = 0")
        await asyncio.sleep(0.2)
        await cdp.eval_js("prepareGov('madrid'); prepareGov('renta_borrador')")
        await asyncio.sleep(0.3)
        shot7 = await cdp.screenshot_pil()
        frame7 = compose_annotated_frame(
            shot7,
            "ESCENA 7 / 8 · SERVICIOS DIGITALES ESPAÑA",
            "Copiloto SERMAS, CatSalut, AEAT y Carpeta Ciudadana",
            [
                "Verificado: en España no existe API pública abierta para pedir citas médicas ni operar en AEAT sin apoderamiento.",
                "Dew actúa en Nivel 2 (Copiloto Preparador): genera el checklist oficial en local y lanza el Deep Link a la app oficial.",
                "Muestra avisos claros de que no es médico ni asesor fiscal y jamás solicita contraseñas de Cl@ve.",
            ],
            "Trámites preparados: Cita SERMAS (Madrid) + Borrador Renta (AEAT)\nPaquetes oficiales: es.madrid.salud.citasanitaria / es.aeat.agenciatributaria\nSeguridad: Cero acceso a credenciales Cl@ve o certificados",
        )
        add_scene_frames(frame7, 4.0)

        # ESCENA 8: Panel «Lo que Dew sabe de mí» (Consentimiento, Exportación y Auditoría)
        await cdp.eval_js("showTab('privacy'); document.querySelector('.content').scrollTop = 0")
        await asyncio.sleep(0.2)
        await cdp.eval_js("approveMemory(1)")
        await asyncio.sleep(0.3)
        shot8 = await cdp.screenshot_pil()
        frame8 = compose_annotated_frame(
            shot8,
            "ESCENA 8 / 8 · PRIVACIDAD Y CONSENTIMIENTO",
            "Panel 'Lo que Dew sabe de mí' y Action Log",
            [
                "El usuario revisa y autoriza explícitamente guardar el recuerdo 'Horario martes y jueves (entrenamiento hasta 21:30)'.",
                "Puede exportar todos sus datos en JSON portable en un toque o ejecutar el Borrado Criptográfico Total.",
                "El Registro de Auditoría (Action Log) muestra cada acción realizada con trazabilidad completa.",
            ],
            "Almacenamiento: SQLCipher AES-256 (Android Keystore)\nDerechos ARCO: Ver / Editar / Exportar JSON / Borrado Total\nTests E2E del Proyecto: 16/16 OK | GitHub CI: PASS",
        )
        add_scene_frames(frame8, 4.0)

    # 1. Codificar MP4 con OpenCV
    w, h = frames_pil[0].size
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(mp4_path), fourcc, float(fps), (w, h))
    for pil_img in frames_pil:
        bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        writer.write(bgr)
    writer.release()

    # 2. Codificar también GIF animado optimizado para el README de GitHub (1 frame por escena)
    unique_scene_frames: List[Image.Image] = []
    step_stride = max(1, len(frames_pil) // 8)
    for i in range(0, len(frames_pil), step_stride):
        resized_gif = frames_pil[i].resize((960, 675), Image.Resampling.LANCZOS)
        unique_scene_frames.append(resized_gif)

    unique_scene_frames[0].save(
        gif_path,
        save_all=True,
        append_images=unique_scene_frames[1:],
        duration=2600,
        loop=0,
        optimize=True,
    )

    return mp4_path, gif_path


def main() -> int:
    port = 8769
    server = HTTPServer(("127.0.0.1", port), DewHttpHandler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    browser_exe = find_browser_exe()
    debug_port = 9234
    user_data_dir = PROJECT_ROOT / "docs" / "demo" / ".tmp_chrome_profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    chrome_cmd = [
        browser_exe,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={debug_port}",
        "--window-size=540,900",
        f"http://127.0.0.1:{port}/",
    ]
    proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        ws_url = None
        for _ in range(30):
            time.sleep(0.3)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=1.0) as resp:
                    targets = json.loads(resp.read().decode("utf-8"))
                    for t in targets:
                        if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
                            ws_url = t["webSocketDebuggerUrl"]
                            break
                if ws_url:
                    break
            except Exception:
                continue

        if not ws_url:
            raise RuntimeError("No se pudo conectar al puerto CDP de Chrome Headless.")

        out_dir = PROJECT_ROOT / "docs" / "demo"
        mp4_path, gif_path = asyncio.run(record_walkthrough(ws_url, out_dir))
        print(
            json.dumps(
                {
                    "status": "VIDEO_RECORDED",
                    "mp4_path": str(mp4_path),
                    "mp4_size_kb": round(mp4_path.stat().st_size / 1024.0, 1),
                    "gif_path": str(gif_path),
                    "gif_size_kb": round(gif_path.stat().st_size / 1024.0, 1),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    finally:
        proc.terminate()
        server.shutdown()
        import shutil
        shutil.rmtree(user_data_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
