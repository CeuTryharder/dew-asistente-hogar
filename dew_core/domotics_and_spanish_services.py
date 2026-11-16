#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conector Domótico Local (Home Assistant LAN / Matter) y Copiloto de Servicios Digitales en España.
Implementa:
  1. Validación determinista de permisos, dispositivos protegidos (`protected=True`),
     fallos de conexión en red local y comandos ambiguos.
  2. Preparación guiada de trámites españoles (Nivel 2: Handoff seguro a `Mi Carpeta Ciudadana`,
     `Cl@ve`, `AEAT` y apps autonómicas de salud) sin pedir jamás credenciales ni automatizar
     portales sin autorización.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso

CRITICAL_SECURITY_DOMAINS = {"lock", "alarm_control_panel", "garage_door", "oven", "heater"}
SAFE_TEMP_MIN_C = 16.0
SAFE_TEMP_MAX_C = 26.0


@dataclass
class SmartDeviceEntity:
    entity_id: str
    friendly_name: str
    domain: str  # 'light', 'climate', 'switch', 'sensor', 'lock', 'alarm_control_panel'
    area: str
    state: str
    online: bool = True
    protected: bool = False  # Ej. enchufe del router, NAS o frigorífico
    attributes: Dict[str, Any] = field(default_factory=dict)


class HomeAssistantLocalConnector:
    """
    Conector domótico agnóstico al fabricante (vía Home Assistant REST/WebSocket en LAN).
    La IA interpreta la petición, pero este motor valida permisos y reglas antes de actuar.
    """

    def __init__(self, storage: DewLocalStorage) -> None:
        self.storage = storage
        self.entities: Dict[str, SmartDeviceEntity] = {}

    def register_entity(self, entity: SmartDeviceEntity) -> None:
        self.entities[entity.entity_id] = entity

    def execute_or_propose_command(
        self,
        entity_id: Optional[str] = None,
        area: Optional[str] = None,
        domain: Optional[str] = None,
        action: str = "turn_off",
        target_celsius: Optional[float] = None,
        user_confirmed_critical: bool = False,
    ) -> Dict[str, Any]:
        """
        Valida y ejecuta (o solicita confirmación si es crítica/ambigua) una orden domótica.
        """
        # 1. Resolver objetivos por entity_id o por área + dominio
        targets: List[SmartDeviceEntity] = []
        if entity_id:
            ent = self.entities.get(entity_id)
            if not ent:
                return {
                    "status": "ERROR_UNKNOWN_DEVICE",
                    "message": f"No encuentro el dispositivo '{entity_id}' en tu hogar.",
                }
            targets = [ent]
        elif area:
            targets = [
                e for e in self.entities.values()
                if e.area.lower() == area.lower() and (domain is None or e.domain == domain)
            ]
            if not targets:
                return {
                    "status": "ERROR_AMBIGUOUS_OR_EMPTY_AREA",
                    "message": f"No hay dispositivos registrados en la zona '{area}'.",
                }
        else:
            return {
                "status": "CLARIFICATION_NEEDED",
                "message": "El comando es ambiguo: ¿en qué habitación o sobre qué dispositivo quieres actuar?",
            }

        executed: List[str] = []
        skipped_protected: List[str] = []
        offline_devices: List[str] = []
        pending_confirmation: List[Dict[str, Any]] = []

        for ent in targets:
            # 2. Comprobar disponibilidad en red local
            if not ent.online:
                offline_devices.append(ent.friendly_name)
                continue

            # 3. Proteger enchufes críticos (router, nevera, servidor) en apagados de grupo
            if ent.protected and action == "turn_off" and entity_id is None:
                skipped_protected.append(ent.friendly_name)
                continue

            # 4. Validar climatización (ambigüedad y límites térmicos)
            if ent.domain == "climate" and action == "set_temperature":
                if target_celsius is None:
                    return {
                        "status": "CLARIFICATION_NEEDED",
                        "entity_id": ent.entity_id,
                        "message": f"¿A cuántos grados (entre {SAFE_TEMP_MIN_C:.0f} y {SAFE_TEMP_MAX_C:.0f} ºC) quieres poner {ent.friendly_name}?",
                    }
                if not (SAFE_TEMP_MIN_C <= target_celsius <= SAFE_TEMP_MAX_C):
                    return {
                        "status": "BLOCKED_BY_SAFETY_RULE",
                        "entity_id": ent.entity_id,
                        "message": (
                            f"Por seguridad y ahorro energético, la temperatura debe estar entre "
                            f"{SAFE_TEMP_MIN_C:.0f} ºC y {SAFE_TEMP_MAX_C:.0f} ºC (solicitado: {target_celsius} ºC)."
                        ),
                    }
                ent.attributes["temperature"] = target_celsius
                ent.state = f"{target_celsius:.1f} ºC"
                executed.append(f"{ent.friendly_name} -> {target_celsius:.1f} ºC")
                continue

            # 5. Exigir confirmación expresa para dominios críticos de seguridad (cerraduras, alarmas, hornos)
            if ent.domain in CRITICAL_SECURITY_DOMAINS and not user_confirmed_critical:
                pending_confirmation.append({
                    "entity_id": ent.entity_id,
                    "friendly_name": ent.friendly_name,
                    "domain": ent.domain,
                    "proposed_action": action,
                    "security_notice": (
                        f"Acción sensible sobre '{ent.friendly_name}' ({action}). "
                        "Requiere confirmación explícita en pantalla."
                    ),
                })
                continue

            # 6. Ejecutar cambio de estado local
            prev_state = ent.state
            if ent.domain == "lock":
                ent.state = "unlocked" if action in ("unlock", "open", "turn_on") else "locked"
            else:
                ent.state = "on" if action in ("turn_on", "unlock", "open") else "off"
            executed.append(f"{ent.friendly_name} ({prev_state} -> {ent.state})")

        if executed:
            self.storage.log_action(
                action_type="DOMOTICS_CONTROL",
                summary="Domótica local: " + ", ".join(executed),
                user_confirmed=user_confirmed_critical,
                new_state={"executed": executed, "skipped_protected": skipped_protected},
            )

        return {
            "status": "PARTIAL_OR_PENDING" if (offline_devices or pending_confirmation) else "OK",
            "executed": executed,
            "skipped_protected": skipped_protected,
            "offline_devices": offline_devices,
            "pending_confirmation": pending_confirmation,
        }


# Catálogo verificado de canales oficiales españoles (Nivel 2: Handoff al ciudadano)
OFFICIAL_SPANISH_HEALTH_SERVICES: Dict[str, Dict[str, str]] = {
    "madrid": {
        "region": "Comunidad de Madrid",
        "org": "SERMAS",
        "app_name": "Cita Sanitaria Madrid",
        "android_package": "es.madrid.salud.citasanitaria",
        "official_url": "https://www.comunidad.madrid/servicios/salud/cita-sanitaria",
        "id_required": "Código CIP de la Tarjeta Sanitaria, DNI/NIE y fecha de nacimiento",
    },
    "cataluna": {
        "region": "Cataluña",
        "org": "CatSalut",
        "app_name": "La Meva Salut",
        "android_package": "cat.gencat.mobi.lamevasalut",
        "official_url": "https://lamevasalut.gencat.cat/",
        "id_required": "Código CIP de la Tarjeta Sanitaria Individual (TSI) o certificado/IdCat Mòbil",
    },
    "andalucia": {
        "region": "Andalucía",
        "org": "Servicio Andaluz de Salud (SAS)",
        "app_name": "Salud Andalucía",
        "android_package": "es.juntadeandalucia.msspa.saludresponde",
        "official_url": "https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/clicsalud/",
        "id_required": "Número AN de Tarjeta Sanitaria, DNI/NIE o Cl@ve",
    },
    "valencia": {
        "region": "Comunitat Valenciana",
        "org": "GVA Salut",
        "app_name": "GVA +Salut",
        "android_package": "es.gva.san.gvasalut",
        "official_url": "https://www.san.gva.es/es/web/portal-del-paciente/cita-previa",
        "id_required": "Número SIP y fecha de nacimiento",
    },
    "pais_vasco": {
        "region": "País Vasco / Euskadi",
        "org": "Osakidetza",
        "app_name": "Portal Móvil Osakidetza",
        "android_package": "eus.osakidetza.portalmovil",
        "official_url": "https://www.osakidetza.euskadi.eus/",
        "id_required": "TIS (Tarjeta Individual Sanitaria) y fecha de nacimiento o BakQ",
    },
    "galicia": {
        "region": "Galicia",
        "org": "SERGAS",
        "app_name": "Sergas Móbil",
        "android_package": "es.sergas.sergasmobil",
        "official_url": "https://cita.sergas.gal/",
        "id_required": "Tarjeta Sanitaria SERGAS o Chave365 / Cl@ve",
    },
}


class SpanishServicesCopilot:
    """
    Asistente Preparador de Trámites en España.
    Distingue estrictamente entre:
      - Nivel 1: Consulta de información pública / datos abiertos (`datos.gob.es`).
      - Nivel 2: Preparación local + Handoff autorizado a la app/web oficial donde el
        ciudadano mantiene el control de su identidad digital (`Cl@ve` / Certificado).
      - Nivel 3: Automatización intrusiva no autorizada (bloqueada por diseño).
    """

    def __init__(self, storage: DewLocalStorage) -> None:
        self.storage = storage

    def prepare_medical_appointment_handoff(
        self,
        region_key: str,
        reason_notes_for_doctor: Optional[str] = None,
        due_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        svc = OFFICIAL_SPANISH_HEALTH_SERVICES.get(
            region_key.lower(), OFFICIAL_SPANISH_HEALTH_SERVICES["madrid"]
        )
        checklist = [
            f"Identificación requerida en la app oficial: {svc['id_required']}.",
            "Revisa tu disponibilidad horaria antes de abrir la aplicación.",
        ]
        if reason_notes_for_doctor:
            checklist.append(f"Puntos anotados para comentar al médico: {reason_notes_for_doctor}")

        cur = self.storage.conn.cursor()
        cur.execute(
            """
            INSERT INTO spanish_procedures_vault
                (title, administration, due_date, checklist_json, official_app_package, official_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"Cita médica en {svc['org']}",
                svc["region"],
                due_date,
                json.dumps(checklist, ensure_ascii=False),
                svc["android_package"],
                svc["official_url"],
                utc_now_iso(),
            ),
        )
        proc_id = int(cur.lastrowid)
        self.storage.conn.commit()

        return {
            "procedure_id": proc_id,
            "integration_tier": "TIER_2_PREPARE_AND_HANDOFF",
            "medical_disclaimer": (
                "AVISO IMPORTANTE: Dew no es médico ni ofrece diagnóstico sanitario. "
                "Solo organiza tus notas y te enlaza con el canal oficial de tu Comunidad Autónoma."
            ),
            "service": svc,
            "checklist": checklist,
            "requires_explicit_user_action": True,
        }

    def prepare_aeat_or_carpeta_ciudadana_handoff(
        self,
        procedure_type: str,  # 'renta_borrador', 'renovacion_dni', 'itv', 'empadronamiento'
        user_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        catalog = {
            "renta_borrador": {
                "title": "Revisión de Datos Fiscales y Borrador de la Renta (IRPF)",
                "administration": "Agencia Estatal de Administración Tributaria (AEAT)",
                "official_app_package": "es.aeat.agenciatributaria",
                "official_url": "https://sede.agenciatributaria.gob.es/",
                "disclaimer": (
                    "AVISO FISCAL: Dew no es asesor fiscal ni presenta declaraciones en tu nombre. "
                    "La confirmación del borrador tiene efectos tributarios y debes realizarla tú mismo en la Sede de la AEAT."
                ),
                "checklist": [
                    "Autenticación necesaria: Cl@ve Móvil, Número de Referencia (casilla 505) o Certificado Digital.",
                    "Revisar deducciones autonómicas aplicables a tu vivienda habitual y familia.",
                    "Comprobar titularidad de cuenta bancaria (IBAN) antes de confirmar.",
                ],
            },
            "renovacion_dni": {
                "title": "Consulta de Vencimiento y Cita Previa para Renovación de DNI/Pasaporte",
                "administration": "Mi Carpeta Ciudadana / Dirección General de la Policía",
                "official_app_package": "es.gob.carpetaciudadana",
                "official_url": "https://carpetaciudadana.gob.es/",
                "disclaimer": "Dew prepara el recordatorio documental; la reserva de cita y el trámite son presenciales/oficiales.",
                "checklist": [
                    "1 fotografía reciente en color con fondo blanco liso.",
                    "DNI anterior (o denuncia previa en caso de extravío/robo).",
                    "Tasa oficial: 12,00 € para DNI (gratuito si se acredita título de Familia Numerosa en vigor).",
                    "Si cambias de domicilio: volante de empadronamiento emitido en los últimos 3 meses.",
                ],
            },
        }
        entry = catalog.get(procedure_type, catalog["renovacion_dni"])
        checklist = list(entry["checklist"])
        if user_notes:
            checklist.append(f"Nota personal guardada en tu móvil: {user_notes}")

        cur = self.storage.conn.cursor()
        cur.execute(
            """
            INSERT INTO spanish_procedures_vault
                (title, administration, due_date, checklist_json, official_app_package, official_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["title"],
                entry["administration"],
                None,
                json.dumps(checklist, ensure_ascii=False),
                entry["official_app_package"],
                entry["official_url"],
                utc_now_iso(),
            ),
        )
        proc_id = int(cur.lastrowid)
        self.storage.conn.commit()

        return {
            "procedure_id": proc_id,
            "integration_tier": "TIER_2_PREPARE_AND_HANDOFF",
            "title": entry["title"],
            "administration": entry["administration"],
            "disclaimer": entry["disclaimer"],
            "checklist": checklist,
            "official_app_package": entry["official_app_package"],
            "official_url": entry["official_url"],
            "requires_explicit_user_action": True,
        }
