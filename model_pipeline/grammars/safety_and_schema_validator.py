#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validador Determinista de Políticas y Seguridad (`Policy & Safety Engine`) para Dew.
Valida toda salida del modelo `Qwen3.8-9B-Distill` antes de permitir cualquier efecto lateral:
  1. Estructura JSON conforme a `dew_tool_schema.json`.
  2. Guardarraíl Químico (`CHEM_GUARD`): bloqueo de mezclas peligrosas en limpieza.
  3. Guardarraíl de Confirmaciones Obligatorias: compras, memoria personal, trámites y
     dispositivos críticos de domótica DEBEN llevar `requires_confirmation = True`.
  4. Rango seguro de climatización domótica (16.0 ºC a 26.0 ºC).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

ALLOWED_TOOLS = {
    "update_inventory",
    "ingest_receipt",
    "confirm_vision_detections",
    "propose_shopping_items",
    "propose_shopping_cart",
    "propose_meal_plan",
    "request_memory_permission",
    "control_home_device",
    "prepare_spanish_procedure",
    "chemical_safety_refusal",
    "none",
}

ALWAYS_CONFIRM_TOOLS = {
    "ingest_receipt",
    "confirm_vision_detections",
    "propose_shopping_items",
    "propose_shopping_cart",
    "propose_meal_plan",
    "request_memory_permission",
    "prepare_spanish_procedure",
}

CRITICAL_DOMOTIC_DOMAINS = {"lock", "alarm_control_panel", "garage_door", "oven", "heater"}

# Pares de reactivos domésticos cuya mezcla nunca debe recomendarse
DANGEROUS_CHEMICAL_GROUPS = [
    ({"lejia", "lejía", "hipoclorito", "cloro"}, {"amoniaco", "amoníaco"}),
    ({"lejia", "lejía", "hipoclorito", "cloro"}, {"vinagre", "acido", "ácido", "antical", "salfuman", "salfumán", "limon", "limón"}),
    ({"lejia", "lejía", "hipoclorito", "cloro"}, {"alcohol", "etanol", "isopropilico", "isopropílico"}),
    ({"agua oxigenada", "peroxido", "peróxido"}, {"vinagre", "acido", "ácido"}),
]


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sanitized_output: Dict[str, Any] | None = None


def detect_chemical_hazard(text: str) -> str | None:
    """Detecta menciones a dos grupos químicos incompatibles en un mismo texto."""
    lower = text.lower()
    for group_a, group_b in DANGEROUS_CHEMICAL_GROUPS:
        found_a = [w for w in group_a if re.search(rf"\b{re.escape(w)}\b", lower)]
        found_b = [w for w in group_b if re.search(rf"\b{re.escape(w)}\b", lower)]
        if found_a and found_b:
            return f"Incompatibilidad química detectada ({found_a[0]} + {found_b[0]})"
    return None


def validate_dew_response(raw_response: str | Dict[str, Any]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    if isinstance(raw_response, str):
        # Si viene con bloque <think>...</think>, separamos el bloque de pensamiento del JSON final
        cleaned = re.sub(r"^<think>.*?</think>\s*", "", raw_response.strip(), flags=re.DOTALL)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return ValidationResult(is_valid=False, errors=[f"JSON inválido: {exc}"])
    elif isinstance(raw_response, dict):
        data = dict(raw_response)
    else:
        return ValidationResult(is_valid=False, errors=["Tipo de respuesta no soportado"])

    for req_key in ("spoken_reply", "thinking_mode_used", "uncertainty_notes", "proposed_actions"):
        if req_key not in data:
            errors.append(f"Falta campo obligatorio '{req_key}'")

    if errors:
        return ValidationResult(is_valid=False, errors=errors)

    spoken_reply = str(data.get("spoken_reply", "")).strip()
    if not (2 <= len(spoken_reply) <= 380):
        errors.append(f"Longitud de spoken_reply fuera de rango ({len(spoken_reply)} caracteres)")

    actions = data.get("proposed_actions", [])
    if not isinstance(actions, list):
        return ValidationResult(is_valid=False, errors=["proposed_actions debe ser una lista"])

    # Verificar seguridad química si menciona reactivos peligrosos sin la herramienta de rechazo
    hazard = detect_chemical_hazard(spoken_reply)
    has_chem_refusal_tool = any(a.get("tool") == "chemical_safety_refusal" for a in actions if isinstance(a, dict))
    if hazard and not has_chem_refusal_tool:
        # Si el texto no contiene una negación explícita ("no mezcles", "nunca mezcles", "prohibido")
        if not re.search(r"\b(no\s+mezcles|nunca\s+mezcles|peligros[oa]|t[oó]xic[oa]|jam[aá]s)\b", spoken_reply.lower()):
            errors.append(f"CHEM_GUARD bloqueó respuesta potencialmente peligrosa: {hazard}")

    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"Acción #{idx} no es un objeto JSON")
            continue
        tool = action.get("tool")
        if tool not in ALLOWED_TOOLS:
            errors.append(f"Herramienta no permitida en acción #{idx}: {tool}")
            continue

        # Forzar confirmación del usuario en herramientas sensibles
        if tool in ALWAYS_CONFIRM_TOOLS and not action.get("requires_confirmation", False):
            warnings.append(f"Forzando requires_confirmation=True en herramienta '{tool}'")
            action["requires_confirmation"] = True

        # Validar reglas domóticas
        if tool == "control_home_device":
            payload = action.get("payload", {})
            domain = payload.get("domain", "")
            if domain in CRITICAL_DOMOTIC_DOMAINS and not action.get("requires_confirmation", False):
                warnings.append(f"Forzando requires_confirmation=True para dominio crítico '{domain}'")
                action["requires_confirmation"] = True

            # Validar límites de temperatura en climatización
            actions_sub = payload.get("actions", [payload])
            for sub in actions_sub:
                if isinstance(sub, dict) and "target_celsius" in sub:
                    temp = sub["target_celsius"]
                    if not isinstance(temp, (int, float)) or not (16.0 <= float(temp) <= 26.0):
                        errors.append(f"Temperatura fuera de rango seguro (16.0-26.0 ºC): {temp}")

    return ValidationResult(
        is_valid=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        sanitized_output=data if len(errors) == 0 else None,
    )
