#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor Interactivo del Simulador Móvil de Dew (`http://127.0.0.1:8765`).
Conecta la interfaz móvil interactiva directamente con `dew_core`:
  - Conmutador de RAM del móvil (8 GB `IQ3_XXS` vs 12 GB+ `Q4_K_M`) y Modo Sin Conexión.
  - Chat por voz/texto con switch dinámico `<think>` vs `<think>\\n</think>` y `CHEM_GUARD`.
  - Escáner OCR de tickets españoles reales (`parse_spanish_receipt_ocr`) y foto de nevera con incertidumbre.
  - Control domótico local con protección de router/nevera y confirmación de cerraduras.
  - Copiloto de trámites españoles (`SERMAS`, `CatSalut`, `SAS`, `AEAT`, `Mi Carpeta Ciudadana`).
  - Panel de Privacidad «Lo que Dew sabe de mí» (Consentimiento, Exportación JSON, Action Log y Borrado).
"""

from __future__ import annotations

import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dew_core.domotics_and_spanish_services import SmartDeviceEntity
from dew_core.hardware_and_orchestrator import DewAssistantOrchestrator
from dew_core.meal_planner import HouseholdPlanningConfig
from dew_core.spanish_receipt_parser import parse_spanish_receipt_ocr

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DewMobileAppState:
    def __init__(self, ram_gb: float = 8.0) -> None:
        self.ram_gb = ram_gb
        self.offline_mode = False
        self.dew = DewAssistantOrchestrator(device_ram_gb=ram_gb)
        self._seed_demo_household()

    def _seed_demo_household(self) -> None:
        # 1. Semilla de memoria aprobada y 1 solicitud pendiente de permiso
        self.dew.storage.save_memory_with_permission(
            key="Comensales y dieta",
            value="2 adultos, sin lactosa",
            category="alimentacion",
            source="Onboarding inicial",
            consent_granted=True,
        )
        self.dew.storage.save_memory_with_permission(
            key="Supermercado y presupuesto",
            value="Mercadona · Objetivo 35,00 €/semana",
            category="compras",
            source="Onboarding inicial",
            consent_granted=True,
        )
        self.dew.storage.request_to_remember(
            key="Horario martes y jueves",
            proposed_value="Entrenamiento hasta las 21:30 (proponer cenas de <10 min)",
            category="rutinas",
            reason="Detectado en conversación reciente",
        )

        # 2. Semilla de inventario (nevera, limpieza e ítem con incertidumbre visual)
        self.dew.inventory.upsert_inventory_item(
            "Queso fresco sin lactosa", "alimentacion", 1, "tarrina 250g",
            confidence=0.96, expiry_in_days=1, last_price_eur=1.45, preferred_store="Mercadona"
        )
        self.dew.inventory.upsert_inventory_item(
            "Huevos camperos", "alimentacion", 6, "unidades",
            confidence=0.94, expiry_in_days=10, last_price_eur=2.60, preferred_store="Mercadona"
        )
        self.dew.inventory.upsert_inventory_item(
            "Táper opaco tapa roja (balda central)", "alimentacion", 1, "unidades",
            confidence=0.42, uncertainty_note="Confianza visual 42%: interior no visible en la foto"
        )
        self.dew.inventory.upsert_inventory_item(
            "Pastillas lavavajillas Bosque Verde", "limpieza", 2, "pastillas",
            location="despensa", confidence=1.0, last_price_eur=4.50, depletion_rate_days=30
        )

        # 3. Cesta borrador inicial
        self.dew.inventory.create_shopping_cart_draft(
            store="Mercadona",
            items=[
                {"name": "Pack 6 Leche sin lactosa Hacendado", "qty": 1, "est_price_eur": 6.30},
                {"name": "Pastillas lavavajillas Bosque Verde", "qty": 1, "est_price_eur": 4.50},
                {"name": "Calabacín malla 1 kg", "qty": 1, "est_price_eur": 1.89},
            ],
            budget_limit_eur=35.0,
        )

        # 4. Dispositivos domóticos en LAN
        self.dew.domotics.register_entity(SmartDeviceEntity(
            "light.salon", "Luz Principal Salón", "light", "salon", "on", online=True
        ))
        self.dew.domotics.register_entity(SmartDeviceEntity(
            "switch.router_nas", "Enchufe Router Fibra / NAS", "switch", "salon", "on", online=True, protected=True
        ))
        self.dew.domotics.register_entity(SmartDeviceEntity(
            "climate.termostato_salon", "Termostato Salón", "climate", "salon", "20.5 ºC", online=False
        ))
        self.dew.domotics.register_entity(SmartDeviceEntity(
            "lock.puerta_calle", "Cerradura Puerta Principal", "lock", "entrada", "locked", online=True
        ))

        # 5. Semilla de alérgenos del hogar e histórico multi-tienda
        self.dew.barcode_service.configure_household_allergens(["lactosa", "cacahuete"], consent_granted=True)
        self.dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Carrefour", 8.45, qty=1, unit="L")
        self.dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Mercadona", 7.65, qty=1, unit="L")
        self.dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Cooperativa Local", 6.90, qty=1, unit="L")

    def snapshot(self) -> Dict[str, Any]:
        exported = self.dew.storage.export_all_user_data()
        pending_reqs = [
            dict(r) for r in self.dew.storage.conn.execute("SELECT * FROM pending_memory_requests").fetchall()
        ]
        alerts = self.dew.inventory.get_low_stock_and_expiring_alerts()
        devices = [
            {
                "entity_id": d.entity_id,
                "friendly_name": d.friendly_name,
                "domain": d.domain,
                "area": d.area,
                "state": d.state,
                "online": d.online,
                "protected": d.protected,
            }
            for d in self.dew.domotics.entities.values()
        ]
        return {
            "ram_gb": self.ram_gb,
            "offline_mode": self.offline_mode,
            "tier": {
                "tier_id": self.dew.tier.tier_id,
                "gguf_filename": self.dew.tier.gguf_filename,
                "quantization": self.dew.tier.quantization,
                "estimated_ram_mb": self.dew.tier.estimated_ram_mb,
                "sequential_unload_required": self.dew.tier.sequential_unload_required,
            },
            "memories": exported["memories"],
            "pending_memory_requests": pending_reqs,
            "inventory": exported["inventory"],
            "alerts": alerts,
            "shopping_carts": exported["shopping_carts"],
            "devices": devices,
            "spanish_procedures": exported["spanish_procedures"],
            "audit_log": exported["audit_log"][:12],
        }


APP_STATE = DewMobileAppState(ram_gb=16.0)


_NON_DOMOTICS_HINTS = ("velocidad de la luz", "años luz", "año luz", "freidora de aire", "en el aire")


def _is_domotics_intent(lower: str) -> bool:
    if any(hint in lower for hint in _NON_DOMOTICS_HINTS):
        return False
    if re.search(r"\b(dom[oó]tica|termostato|cerradura|home assistant)\b", lower):
        return True
    if re.search(
        r"\b(apaga|apagar|enciende|encender|abre|abrir|cierra|cerrar|sube|subir|baja|bajar|desbloquea|bloquea|conecta|desconecta)\b"
        r".*\b(luz|luces|l[aá]mpara|sal[oó]n|cocina|dormitorio|calefacci[oó]n|puerta|persiana|enchufe|todo)\b",
        lower,
    ):
        return True
    return bool(re.search(r"\b(luz|luces|puerta)\b.*\b(sal[oó]n|cocina|entrada|apaga|enciende|abre|cierra)\b", lower))


def _is_spanish_gov_intent(lower: str) -> bool:
    if re.search(r"\b(cita)\s+(m[eé]dic\w*|sanitar\w*|salud|previa|dgt|dni|nie|aeat|hacienda|padr[oó]n)\b", lower):
        return True
    if re.search(r"\b(pedir|solicitar|sacar|renovar|consultar|revisar|preparar)\s+.*?\b(cita|dni|nie|renta|borrador|hacienda|aeat|empadronamiento)\b", lower):
        return True
    return bool(re.search(r"\b(hacienda|aeat|borrador de la renta|carpeta ciudadana|cl@ve|empadronamiento|sermas|catsalut)\b", lower))


def handle_api_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")

    if action == "switch_hardware_ram":
        new_ram = float(payload.get("ram_gb", 8.0))
        APP_STATE.ram_gb = new_ram
        from dew_core.hardware_and_orchestrator import HardwareModelSelector, SequentialMemoryManager
        APP_STATE.dew.tier = HardwareModelSelector.select_tier_for_device(new_ram)
        APP_STATE.dew.memory_mgr = SequentialMemoryManager(APP_STATE.dew.tier.sequential_unload_required)
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "toggle_offline":
        APP_STATE.offline_mode = bool(payload.get("offline", False))
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "voice_or_text_turn":
        utterance = str(payload.get("utterance", "")).strip()
        lower = utterance.lower()
        chem_check = APP_STATE.dew.inventory.validate_cleaning_advice_safety(utterance)
        built = APP_STATE.dew.prepare_voice_turn(utterance)
        think_trace = (
            f"[ORCA-DEW KERNEL] Model={APP_STATE.dew.tier.tier_id} | Mode={built.mode}\n"
            f"[CONTEXT] Query='{utterance}' | Inventory={len(APP_STATE.dew.storage.export_all_user_data()['inventory'])} items"
        )
        if not chem_check["safe"]:
            reply = chem_check["safe_replacement_message"]
            chem_hazard = chem_check["hazard"]
            think_trace += f"\n[CHEM_GUARD] BLOCKED dangerous chemical mixture -> {chem_hazard}"
        elif _is_domotics_intent(lower):
            if re.search(r"\b(puerta|cerradura)\b", lower):
                lock_action = "unlock" if re.search(r"\b(abre|abrir|desbloquea|destraba)\b", lower) else "lock"
                res = APP_STATE.dew.domotics.execute_or_propose_command(
                    entity_id="lock.puerta_calle",
                    action=lock_action,
                    user_confirmed_critical=False,
                )
                reply = (
                    f"🔐 Seguridad LAN: '{lock_action}' sobre Cerradura Puerta Principal requiere confirmación "
                    f"explícita ({len(res.get('pending_confirmation', []))} pendiente)."
                )
                think_trace += f"\n[TOOL_EXEC] home_assistant.lock_guard('lock.puerta_calle', '{lock_action}') -> PENDING_CONFIRMATION"
            else:
                turn_action = "turn_off" if re.search(r"\b(apaga|apagar|cierra|cerrar|desconecta)\b", lower) else "turn_on"
                res = APP_STATE.dew.domotics.execute_or_propose_command(
                    area="salon",
                    action=turn_action,
                    user_confirmed_critical=False,
                )
                reply = (
                    f"🏠 Domótica LAN ejecutada: actuados {res.get('executed', [])}. "
                    f"Protegidos sin apagar: {res.get('skipped_protected', [])}."
                )
                think_trace += f"\n[TOOL_EXEC] home_assistant.area_command('salon', '{turn_action}') -> {res.get('executed', [])}"
            chem_hazard = None
        elif _is_spanish_gov_intent(lower):
            is_health = bool(re.search(r"\b(m[eé]dic\w*|sanitar\w*|salud|sermas|catsalut)\b", lower))
            svc = "madrid" if is_health else "renta_borrador"
            if svc == "madrid":
                proc = APP_STATE.dew.spanish_services.prepare_medical_appointment_handoff("madrid", utterance)
            else:
                proc = APP_STATE.dew.spanish_services.prepare_aeat_or_carpeta_ciudadana_handoff("renta_borrador", utterance)
            reply = (
                f"🏛️ Expediente preparado en local: {proc['title']} ({proc['administration']}). "
                f"Checklist generado sin pedir tus claves Cl@ve. Sede oficial: {proc['official_url']}"
            )
            chem_hazard = None
            think_trace += f"\n[TOOL_EXEC] spanish_gov.prepare_handoff('{svc}') -> READY"
        elif built.mode == "deep_think" or any(k in lower for k in ("planifica", "menú", "menu", "cena", "presupuesto")):
            cfg = HouseholdPlanningConfig(diners_count=2, weekly_budget_limit_eur=35.0, preferred_store="Mercadona", dietary_restrictions=["sin_lactosa"])
            plan_res = APP_STATE.dew.meal_planner.generate_plan_and_shopping_cart(cfg)
            titles = ", ".join(f"{d['day']}: {d['title']}" for d in plan_res["meal_plan"][:3])
            reply = (
                f"🍲 Planificación <think> completada (Presupuesto 35,00 €): {titles}... "
                f"Cesta generada en Mercadona por {plan_res['budget_summary']['estimated_total_eur']:.2f} €."
            )
            chem_hazard = None
            think_trace += f"\n[THINK] Priorizando Queso fresco (caduca 24h) -> Cesta={plan_res['budget_summary']['estimated_total_eur']:.2f}€"
        else:
            if "tortilla" in lower:
                reply = (
                    "🍳 Tortilla de Patatas Española Perfecta: 6 huevos camperos por 700 g de patata Monalisa. "
                    "Confita la patata 18 min a 140 °C, mézclala en caliente con el huevo batido dejando reposar "
                    "10 min y cuájala 1,5 min por cara a fuego vivo."
                )
            elif "iva" in lower:
                reply = (
                    "🧮 Cálculo de IVA (21%): multiplica la base por 0,21 para la cuota de IVA (o por 1,21 para el total). "
                    "Si el precio ya incluye IVA, divide entre 1,21 para obtener la base imponible."
                )
            elif "python" in lower or "código" in lower or "codigo" in lower:
                reply = (
                    "💻 [Orca Code Engine]: Puedo generarte scripts en Python, Bash, Kotlin o SQL optimizados para "
                    "ejecución local en ARM64 / Snapdragon."
                )
            elif "agujero negro" in lower or "relatividad" in lower:
                reply = (
                    "🌌 Según la Relatividad General de Einstein (1915), un agujero negro es una región del espacio-tiempo "
                    "cuya curvatura gravitatoria impide que escape incluso la luz (velocidad c = 299.792,458 km/s)."
                )
            else:
                inv = APP_STATE.dew.storage.export_all_user_data()["inventory"]
                inv_names = ", ".join(f"{i['normalized_name']} ({i['qty']} {i['unit']})" for i in inv[:4])
                reply = (
                    f"🤖 [Orca·Dew Modo Abierto]: Respuesta directa para «{utterance}». "
                    f"(Contexto activo del hogar: {inv_names})."
                )
            chem_hazard = None
            think_trace += "\n[OPEN_DOMAIN_LLM] Consulta general resuelta en 180 ms (39.4 tok/s · Vulkan GPU)"

        return {
            "ok": True,
            "turn_result": {
                "utterance": utterance,
                "mode": built.mode,
                "grammar_file": built.grammar_file,
                "spoken_reply": reply,
                "think_trace": think_trace,
                "chemical_hazard": chem_hazard,
                "memory_transitions": list(APP_STATE.dew.memory_mgr.transition_history[-3:]),
            },
            "state": APP_STATE.snapshot(),
        }

    if action == "scan_spanish_receipt":
        raw_ocr = str(payload.get("raw_ocr", ""))
        parsed = parse_spanish_receipt_ocr(raw_ocr)
        for item in parsed["items"]:
            APP_STATE.dew.inventory.upsert_inventory_item(
                normalized_name=item["normalized_name"],
                category=item["category"],
                qty=item["qty"],
                unit=item["unit"],
                confidence=1.0,
                last_price_eur=item["unit_price_eur"],
                preferred_store=parsed["store"],
                expiry_in_days=item["estimated_expiry_days"],
                depletion_rate_days=item["estimated_depletion_days"],
                user_confirmed=True,
            )
        return {"ok": True, "parsed_receipt": parsed, "state": APP_STATE.snapshot()}

    if action == "resolve_fridge_uncertainty":
        old_name = str(payload.get("old_name", ""))
        confirmed_name = str(payload.get("confirmed_name", "Lentejas caseras en táper"))
        APP_STATE.dew.storage.conn.execute(
            "DELETE FROM inventory_items WHERE normalized_name = ?", (old_name,)
        )
        APP_STATE.dew.inventory.upsert_inventory_item(
            normalized_name=confirmed_name,
            category="alimentacion",
            qty=1.0,
            unit="táper",
            confidence=1.0,
            expiry_in_days=2,
            user_confirmed=True,
        )
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "confirm_cart":
        cart_id = int(payload.get("cart_id", 1))
        APP_STATE.dew.inventory.confirm_shopping_cart(cart_id)
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "domotics_command":
        res = APP_STATE.dew.domotics.execute_or_propose_command(
            entity_id=payload.get("entity_id"),
            area=payload.get("area"),
            action=payload.get("domotic_action", "turn_off"),
            user_confirmed_critical=bool(payload.get("user_confirmed_critical", False)),
        )
        return {"ok": True, "domotics_result": res, "state": APP_STATE.snapshot()}

    if action == "prepare_spanish_service":
        svc_type = str(payload.get("service_type", "sermas"))
        if svc_type in ("madrid", "cataluna", "andalucia", "valencia"):
            res = APP_STATE.dew.spanish_services.prepare_medical_appointment_handoff(
                region_key=svc_type,
                reason_notes_for_doctor=payload.get("notes", "Consulta de control"),
            )
        else:
            res = APP_STATE.dew.spanish_services.prepare_aeat_or_carpeta_ciudadana_handoff(
                procedure_type=svc_type,
                user_notes=payload.get("notes"),
            )
        return {"ok": True, "procedure_result": res, "state": APP_STATE.snapshot()}

    if action == "approve_memory":
        req_id = int(payload.get("request_id"))
        APP_STATE.dew.storage.confirm_memory_request(req_id)
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "wipe_all_data":
        APP_STATE.dew.storage.wipe_all_user_data()
        return {"ok": True, "state": APP_STATE.snapshot()}

    if action == "generate_flexible_plan":
        diners = int(payload.get("diners_count", 2))
        raw_budget = payload.get("budget_eur")
        budget_limit = float(raw_budget) if (raw_budget is not None and str(raw_budget).strip() != "") else None
        store = str(payload.get("preferred_store", "Mercadona")).strip() or "Tu supermercado"
        cfg = HouseholdPlanningConfig(
            diners_count=diners,
            weekly_budget_limit_eur=budget_limit,
            preferred_store=store,
            dietary_restrictions=["sin_lactosa"],
        )
        plan_res = APP_STATE.dew.meal_planner.generate_plan_and_shopping_cart(cfg)
        return {"ok": True, "plan_result": plan_res, "state": APP_STATE.snapshot()}

    if action == "scan_barcode_ean13":
        ean13 = str(payload.get("ean13", "")).strip()
        allergens_raw = str(payload.get("custom_allergens", "")).strip()
        if allergens_raw:
            APP_STATE.dew.barcode_service.configure_household_allergens(
                [x.strip() for x in allergens_raw.split(",") if x.strip()], consent_granted=True
            )
        scan_res = APP_STATE.dew.barcode_service.scan_barcode(ean13, qty_to_add=1.0)
        return {"ok": True, "scan_result": scan_res, "state": APP_STATE.snapshot()}

    if action == "compare_prices":
        query = str(payload.get("product_query", "Aceite")).strip()
        comp = APP_STATE.dew.history_search.compare_product_prices_across_stores(query)
        return {"ok": True, "price_comparison": comp, "state": APP_STATE.snapshot()}

    return {"ok": False, "error": f"Acción desconocida: {action}"}


class DewHttpHandler(BaseHTTPRequestHandler):
    _STATIC_ROUTES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/manifest.json": ("manifest.json", "application/manifest+json; charset=utf-8"),
        "/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
        "/icon.svg": ("icon.svg", "image/svg+xml; charset=utf-8"),
    }

    def _serve_get_or_head(self, include_body: bool) -> None:
        clean_path = self.path.split("?", 1)[0]
        extra_headers: Dict[str, str] = {}
        body: bytes | None = None
        content_type = "application/octet-stream"

        if clean_path in self._STATIC_ROUTES:
            filename, content_type = self._STATIC_ROUTES[clean_path]
            file_path = STATIC_DIR / filename
            if file_path.exists():
                body = file_path.read_bytes()
        elif clean_path == "/dew-hogar-redmagic-16gb-debug.apk":
            apk_file = PROJECT_ROOT / "dist" / "dew-hogar-redmagic-16gb-debug.apk"
            if apk_file.exists():
                body = apk_file.read_bytes() if include_body else None
                content_type = "application/vnd.android.package-archive"
                extra_headers["Content-Disposition"] = 'attachment; filename="dew-hogar-redmagic-16gb-debug.apk"'
                content_length = apk_file.stat().st_size
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                for key, val in extra_headers.items():
                    self.send_header(key, val)
                self.send_header("Content-Length", str(content_length))
                self.end_headers()
                if include_body and body is not None:
                    self.wfile.write(body)
                return
        elif clean_path == "/api/state":
            content_type = "application/json; charset=utf-8"
            body = json.dumps(APP_STATE.snapshot(), ensure_ascii=False).encode("utf-8")

        if body is None:
            if include_body:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self._serve_get_or_head(include_body=False)

    def do_GET(self) -> None:
        self._serve_get_or_head(include_body=True)

    def do_POST(self) -> None:
        if self.path == "/api/action":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw) if raw else {}
            res = handle_api_action(payload)
            body = json.dumps(res, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer((host, port), DewHttpHandler)
    print(f"Simulador Móvil de Dew activo en http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
