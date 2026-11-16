#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parser Determinista de Tickets de Supermercados Españoles (OCR Local -> Inventario Estructurado).
Soporta los formatos habituales de tickets en España:
  - Mercadona (Hacendado / Bosque Verde / Deliplus)
  - Carrefour / Carrefour Express
  - Consum / Dia / Eroski / Lidl / Alcampo

¿Por qué un parser híbrido (Reglas + Normalización léxica antes del 9B)?
En el móvil, ML Kit OCR extrae el texto en <25 ms. Este parser estructura líneas, precios
en formato español (`1,85`, `12,40`), cantidades y categorías (`alimentacion` vs `limpieza`)
al instante, incluso mientras el modelo 9B se está descargando o en modo ahorro de batería.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

STORE_PATTERNS = {
    "Mercadona": re.compile(r"\b(mercadona|hacendado|bosque\s+verde)\b", re.IGNORECASE),
    "Carrefour": re.compile(r"\b(carrefour|centros\s+comerciales\s+carrefour)\b", re.IGNORECASE),
    "Consum": re.compile(r"\b(consum\s+s\.?coop|consum)\b", re.IGNORECASE),
    "Dia": re.compile(r"\b(distribuidora\s+internacional\s+de\s+alimentaci[oó]n|supermercados\s+dia|\bdia\b)\b", re.IGNORECASE),
    "Eroski": re.compile(r"\b(eroski)\b", re.IGNORECASE),
    "Lidl": re.compile(r"\b(lidl\s+supermercados|\blidl\b)\b", re.IGNORECASE),
    "Alcampo": re.compile(r"\b(alcampo|auchan)\b", re.IGNORECASE),
}

# Diccionario de abreviaturas frecuentes en tickets españoles
SPANISH_RECEIPT_ABBREVIATIONS: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bL\.?\s*ENT\.?\s*S/LACT\b", re.I), "Leche entera sin lactosa"),
    (re.compile(r"\bL\.?\s*SEMI\.?\s*S/LACT\b", re.I), "Leche semidesnatada sin lactosa"),
    (re.compile(r"\bS/LACT(OSA)?\b", re.I), "sin lactosa"),
    (re.compile(r"\bS/GLUT(EN)?\b", re.I), "sin gluten"),
    (re.compile(r"\bPECH\.?\s*PAVO\s*LONCH\w*\b", re.I), "Pechuga de pavo en lonchas"),
    (re.compile(r"\bPECH\.?\s*POLLO\b", re.I), "Pechuga de pollo"),
    (re.compile(r"\bDETERG\.?\s*ROPA\b", re.I), "Detergente líquido ropa"),
    (re.compile(r"\bPAST\.?\s*LAVAVAJ\w*\b", re.I), "Pastillas lavavajillas"),
    (re.compile(r"\bLAVAVAJ\.?\s*MANO\b", re.I), "Lavavajillas a mano concentrado"),
    (re.compile(r"\bPAPEL\s*HIG\w*\b", re.I), "Papel higiénico"),
    (re.compile(r"\bBOLSAS?\s*BASURA\b", re.I), "Bolsas de basura"),
    (re.compile(r"\bHAC(ENDADO)?\b", re.I), "Hacendado"),
    (re.compile(r"\bB\.?\s*VERDE\b", re.I), "Bosque Verde"),
]

CLEANING_KEYWORDS = re.compile(
    r"\b(deterg\w*|lavavaj\w*|lej[ií]a|amoniaco|fregasuelos|antical|suavizante|"
    r"papel\s+higi[eé]nico|papel\s+cocina|bolsas?\s+basura|estropajo\w*|bayeta\w*|"
    r"bosque\s+verde|quitagrasas|limpiacristales|jab[oó]n\s+marsella)\b",
    re.IGNORECASE,
)

# Caducidad estimada por defecto según tipo de alimento (en días)
SHELF_LIFE_ESTIMATES: List[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\b(merluza|salm[oó]n|pescado|carne\s+picada|pollo|pavo\s+fresco)\b", re.I), 3),
    (re.compile(r"\b(queso\s+fresco|espinacas|ensalada|lechuga|fresas)\b", re.I), 5),
    (re.compile(r"\b(calabac[ií]n|br[oó]coli|tomate|pl[aá]tano|lonchas)\b", re.I), 7),
    (re.compile(r"\b(yogur|huevos)\b", re.I), 18),
    (re.compile(r"\b(leche|garbanzo|lenteja|arroz|pasta|at[uú]n|aceite)\b", re.I), 60),
]

# Patrón de línea de ticket: "<cantidad opcional> <descripción> <precio unitario opcional> <importe total>"
RECEIPT_LINE_RE = re.compile(
    r"^\s*(?:(?P<qty>\d+(?:[.,]\d+)?)\s*(?:x|uds?|kg)?\s+)?"
    r"(?P<desc>[A-ZÁÉÍÓÚÑa-záéíóúñ0-9./\-\s]{3,42}?)\s+"
    r"(?:(?P<unit_price>\d{1,3}[.,]\d{2})\s+)?"
    r"(?P<total_price>\d{1,3}[.,]\d{2})\s*(?:€|EUR|A|B)?\s*$"
)

IGNORE_LINE_RE = re.compile(
    r"\b(total|subtotal|iva|base\s+imponible|tarjeta\s+bancaria|efectivo|cambio|"
    r"gracias\s+por\s+su\s+visita|aut\.|factura\s+simplificada|c\.?i\.?f\.?|n\.?i\.?f\.?)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedReceiptItem:
    raw_line: str
    normalized_name: str
    category: str
    qty: float
    unit: str
    total_price_eur: float
    unit_price_eur: float
    estimated_expiry_days: Optional[int]
    estimated_depletion_days: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_line": self.raw_line,
            "normalized_name": self.normalized_name,
            "category": self.category,
            "qty": self.qty,
            "unit": self.unit,
            "total_price_eur": self.total_price_eur,
            "unit_price_eur": self.unit_price_eur,
            "estimated_expiry_days": self.estimated_expiry_days,
            "estimated_depletion_days": self.estimated_depletion_days,
        }


def detect_store_name(raw_ocr_text: str) -> str:
    for store_name, pattern in STORE_PATTERNS.items():
        if pattern.search(raw_ocr_text):
            return store_name
    return "Supermercado local"


def normalize_spanish_product_name(raw_desc: str) -> str:
    cleaned = raw_desc.strip()
    for pattern, replacement in SPANISH_RECEIPT_ABBREVIATIONS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.isupper():
        cleaned = cleaned.capitalize()
    return cleaned


def estimate_shelf_life_or_depletion(normalized_name: str, category: str) -> tuple[Optional[int], Optional[int]]:
    if category == "limpieza":
        return (None, 30)
    for pattern, days in SHELF_LIFE_ESTIMATES:
        if pattern.search(normalized_name):
            return (days, None)
    return (14, None)


def parse_spanish_receipt_ocr(raw_ocr_text: str) -> Dict[str, Any]:
    """
    Convierte el texto bruto de un ticket de compra español en una lista estructurada
    de productos lista para actualizar el inventario y el histórico de precios.
    """
    store = detect_store_name(raw_ocr_text)
    items: List[ParsedReceiptItem] = []

    for line in raw_ocr_text.splitlines():
        stripped = line.strip()
        if not stripped or IGNORE_LINE_RE.search(stripped):
            continue

        match = RECEIPT_LINE_RE.match(stripped)
        if not match:
            continue

        desc_raw = match.group("desc").strip()
        if len(desc_raw) < 3 or desc_raw.isdigit():
            continue

        qty_str = match.group("qty")
        qty = float(qty_str.replace(",", ".")) if qty_str else 1.0
        total_price = float(match.group("total_price").replace(",", "."))
        unit_price_str = match.group("unit_price")
        unit_price = float(unit_price_str.replace(",", ".")) if unit_price_str else round(total_price / (qty if qty > 0 else 1.0), 2)

        normalized_name = normalize_spanish_product_name(desc_raw)
        category = "limpieza" if CLEANING_KEYWORDS.search(normalized_name) else "alimentacion"
        unit = "kg" if re.search(r"\b(\d+\s*kg|malla\s*1kg|granel)\b", desc_raw, re.I) else "unidades"
        expiry_days, depletion_days = estimate_shelf_life_or_depletion(normalized_name, category)

        items.append(
            ParsedReceiptItem(
                raw_line=stripped,
                normalized_name=normalized_name,
                category=category,
                qty=qty,
                unit=unit,
                total_price_eur=total_price,
                unit_price_eur=unit_price,
                estimated_expiry_days=expiry_days,
                estimated_depletion_days=depletion_days,
            )
        )

    calculated_total = round(sum(i.total_price_eur for i in items), 2)
    return {
        "store": store,
        "item_count": len(items),
        "calculated_total_eur": calculated_total,
        "requires_user_confirmation": True,
        "items": [i.to_dict() for i in items],
    }
