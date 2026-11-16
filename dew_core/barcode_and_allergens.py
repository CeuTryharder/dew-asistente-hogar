#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Escáner de Códigos de Barras (`EAN-13`), Caché Offline de Productos (`Open Food Facts España`)
y Detector Flexible de Alérgenos e Ingredientes Evitados por el Usuario.

Flexibilidad total para el usuario:
  1. Cada hogar puede configurar libremente su lista de alérgenos o ingredientes a evitar
     (lactosa, gluten, frutos secos, huevo, marisco, soja, fructosa, aceite de palma o cualquier
     término libre definido por el usuario).
  2. El usuario puede registrar o personalizar cualquier código de barras, marca, tienda y precio.
  3. Funciona 100% sin conexión sobre la tabla local `barcode_catalog_cache`, y opcionalmente
     consulta `es.openfoodfacts.org` cuando hay internet y el usuario escanea un producto nuevo.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from dew_core.inventory_and_shopping import InventoryAndShoppingEngine
from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso

# Diccionario de sinónimos para ampliar términos de alergias/intolerancias configurados por el usuario
ALLERGEN_SYNONYMS: Dict[str, List[str]] = {
    "lactosa": ["lactosa", "leche", "suero lácteo", "suero de leche", "mantequilla", "nata", "queso", "milk", "lactose"],
    "leche": ["leche", "lactosa", "suero lácteo", "caseína", "mantequilla", "nata", "milk"],
    "gluten": ["gluten", "trigo", "cebada", "centeno", "espelta", "kamut", "wheat", "barley"],
    "frutos_secos": ["frutos secos", "frutos de cáscara", "almendra", "avellana", "nuez", "nueces", "cacahuete", "pistacho", "anacardo", "nuts", "peanuts"],
    "huevo": ["huevo", "albumina", "albúmina", "lecitina de huevo", "egg"],
    "soja": ["soja", "lecitina de soja", "soy", "soya"],
    "marisco": ["marisco", "crustáceos", "gamba", "langostino", "moluscos", "crustaceans", "shellfish"],
    "pescado": ["pescado", "atún", "merluza", "salmón", "anchoa", "fish"],
}

DEFAULT_SPANISH_BARCODE_SEED: List[Dict[str, Any]] = [
    {
        "ean13": "8480000107046",
        "product_name": "Leche semidesnatada sin lactosa Hacendado",
        "brand": "Hacendado",
        "category": "alimentacion",
        "default_unit": "brick_1L",
        "reference_price_eur": 1.05,
        "allergens": [],
        "ingredients_text": "Leche semidesnatada de vaca y enzima lactasa (0% lactosa).",
    },
    {
        "ean13": "8480000105011",
        "product_name": "Leche entera UHT Hacendado",
        "brand": "Hacendado",
        "category": "alimentacion",
        "default_unit": "brick_1L",
        "reference_price_eur": 0.95,
        "allergens": ["leche", "lactosa"],
        "ingredients_text": "Leche entera de vaca (contiene lactosa).",
    },
    {
        "ean13": "8480000231406",
        "product_name": "Crema de cacahuete 100% Hacendado",
        "brand": "Hacendado",
        "category": "alimentacion",
        "default_unit": "bote_500g",
        "reference_price_eur": 2.85,
        "allergens": ["frutos_secos", "cacahuete"],
        "ingredients_text": "100% cacahuetes tostados. Puede contener trazas de otros frutos de cáscara.",
    },
    {
        "ean13": "8480000441126",
        "product_name": "Detergente líquido ropa hipoalergénico Bosque Verde",
        "brand": "Bosque Verde",
        "category": "limpieza",
        "default_unit": "botella_45_lavados",
        "reference_price_eur": 5.45,
        "allergens": [],
        "ingredients_text": "Tensioactivos aniónicos y no iónicos, jabón, perfume hipoalergénico.",
    },
]


class BarcodeAndAllergenService:
    def __init__(self, storage: DewLocalStorage, inventory_engine: InventoryAndShoppingEngine) -> None:
        self.storage = storage
        self.inventory = inventory_engine
        self._init_barcode_tables()
        self._seed_default_barcodes()

    def _init_barcode_tables(self) -> None:
        self.storage.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS barcode_catalog_cache (
                ean13 TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                brand TEXT,
                category TEXT NOT NULL DEFAULT 'alimentacion',
                default_unit TEXT NOT NULL DEFAULT 'unidades',
                reference_price_eur REAL,
                allergens_json TEXT NOT NULL DEFAULT '[]',
                ingredients_text TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'local',
                updated_at TEXT NOT NULL
            );
            """
        )
        self.storage.conn.commit()

    def _seed_default_barcodes(self) -> None:
        for item in DEFAULT_SPANISH_BARCODE_SEED:
            self.upsert_custom_barcode_product(
                ean13=item["ean13"],
                product_name=item["product_name"],
                brand=item["brand"],
                category=item["category"],
                default_unit=item["default_unit"],
                reference_price_eur=item["reference_price_eur"],
                allergens=item["allergens"],
                ingredients_text=item["ingredients_text"],
                source="seed_es",
            )

    def upsert_custom_barcode_product(
        self,
        ean13: str,
        product_name: str,
        brand: str = "",
        category: str = "alimentacion",
        default_unit: str = "unidades",
        reference_price_eur: Optional[float] = None,
        allergens: Optional[List[str]] = None,
        ingredients_text: str = "",
        source: str = "user_custom",
    ) -> Dict[str, Any]:
        """Permite al usuario registrar o personalizar cualquier producto por código de barras."""
        clean_ean = ean13.strip()
        allergens_list = allergens or []
        now = utc_now_iso()
        self.storage.conn.execute(
            """
            INSERT INTO barcode_catalog_cache (
                ean13, product_name, brand, category, default_unit,
                reference_price_eur, allergens_json, ingredients_text, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ean13) DO UPDATE SET
                product_name = excluded.product_name,
                brand = excluded.brand,
                category = excluded.category,
                default_unit = excluded.default_unit,
                reference_price_eur = COALESCE(excluded.reference_price_eur, barcode_catalog_cache.reference_price_eur),
                allergens_json = excluded.allergens_json,
                ingredients_text = excluded.ingredients_text,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                clean_ean,
                product_name.strip(),
                brand.strip(),
                category,
                default_unit,
                reference_price_eur,
                json.dumps(allergens_list, ensure_ascii=False),
                ingredients_text,
                source,
                now,
            ),
        )
        self.storage.conn.commit()
        return self.get_cached_product(clean_ean)  # type: ignore[return-value]

    def get_cached_product(self, ean13: str) -> Optional[Dict[str, Any]]:
        row = self.storage.conn.execute(
            "SELECT * FROM barcode_catalog_cache WHERE ean13 = ?", (ean13.strip(),)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["allergens"] = json.loads(d.pop("allergens_json", "[]"))
        return d

    def configure_household_allergens(
        self, allergens_or_avoided: List[str], consent_granted: bool = True
    ) -> List[str]:
        """
        Guarda con consentimiento del usuario la lista personalizada de alérgenos o
        ingredientes evitados en el hogar.
        """
        cleaned = [a.strip().lower() for a in allergens_or_avoided if a.strip()]
        self.storage.save_memory_with_permission(
            key="alergenos_e_ingredientes_evitados",
            value=", ".join(cleaned),
            category="salud_alimentaria",
            source="Configurado por el usuario",
            consent_granted=consent_granted,
        )
        return cleaned

    def get_household_allergens(self) -> List[str]:
        mem = self.storage.get_memory("alergenos_e_ingredientes_evitados")
        if not mem or not mem.get("value"):
            return []
        return [x.strip().lower() for x in str(mem["value"]).split(",") if x.strip()]

    def check_product_against_user_allergens(
        self, product: Dict[str, Any], custom_allergens_override: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Comprueba si el producto contiene algún alérgeno o ingrediente que el usuario haya
        configurado evitar. Respeta explícitamente menciones 'sin lactosa' o 'sin gluten'.
        """
        user_allergens = (
            [a.lower() for a in custom_allergens_override]
            if custom_allergens_override is not None
            else self.get_household_allergens()
        )
        if not user_allergens:
            return {"safe_for_household": True, "conflicts": [], "warning_message": None}

        prod_name_lower = str(product.get("product_name", "")).lower()
        ing_lower = str(product.get("ingredients_text", "")).lower()
        declared_allergens = {str(a).lower() for a in product.get("allergens", [])}

        conflicts: List[str] = []
        for user_alg in user_allergens:
            # Si el producto declara expresamente ser "sin <alérgeno>" o "(0% <alérgeno>)" (sin confundir con 100%)
            free_pattern = re.compile(rf"(?:(?<!\d)0%\s+{re.escape(user_alg)}\b|\bsin\s+{re.escape(user_alg)}\b)", re.I)
            if free_pattern.search(prod_name_lower) or free_pattern.search(ing_lower):
                continue

            synonyms = ALLERGEN_SYNONYMS.get(user_alg, [user_alg])
            matched = False
            if user_alg in declared_allergens or any(s in declared_allergens for s in synonyms):
                matched = True
            elif any(s in ing_lower for s in synonyms):
                matched = True

            if matched:
                conflicts.append(user_alg)

        if conflicts:
            joined = ", ".join(conflicts)
            return {
                "safe_for_household": False,
                "conflicts": conflicts,
                "warning_message": (
                    f"AVISO DE ALÉRGENOS: '{product.get('product_name')}' contiene o puede contener "
                    f"[{joined}], que figura en tu lista de restricciones del hogar."
                ),
            }
        return {"safe_for_household": True, "conflicts": [], "warning_message": None}

    def scan_barcode(
        self,
        ean13: str,
        qty_to_add: float = 1.0,
        user_price_eur: Optional[float] = None,
        auto_add_if_safe: bool = True,
        allow_online_openfoodfacts: bool = False,
    ) -> Dict[str, Any]:
        """
        Escanea un código EAN-13:
          1. Busca primero en la caché SQLite local (<2 ms).
          2. Si no existe y `allow_online_openfoodfacts=True`, consulta `es.openfoodfacts.org`.
          3. Verifica compatibilidad con los alérgenos configurados por el usuario.
          4. Si es seguro y `auto_add_if_safe=True`, actualiza el inventario local.
        """
        product = self.get_cached_product(ean13)
        if product is None and allow_online_openfoodfacts:
            product = self._fetch_from_openfoodfacts_es(ean13)

        if product is None:
            return {
                "found": False,
                "ean13": ean13,
                "message": (
                    f"Código {ean13} no registrado aún en tu móvil. "
                    "Puedes decirme su nombre y precio por voz para guardarlo en tu catálogo local."
                ),
            }

        allergen_check = self.check_product_against_user_allergens(product)
        final_price = user_price_eur if user_price_eur is not None else product.get("reference_price_eur")

        added_to_inventory = False
        if auto_add_if_safe and allergen_check["safe_for_household"]:
            self.inventory.upsert_inventory_item(
                normalized_name=product["product_name"],
                category=product["category"],
                qty=qty_to_add,
                unit=product["default_unit"],
                confidence=1.0,
                last_price_eur=final_price,
                user_confirmed=True,
            )
            added_to_inventory = True

        return {
            "found": True,
            "ean13": ean13,
            "product": product,
            "allergen_check": allergen_check,
            "added_to_inventory": added_to_inventory,
        }

    def _fetch_from_openfoodfacts_es(self, ean13: str) -> Optional[Dict[str, Any]]:
        url = f"https://es.openfoodfacts.org/api/v2/product/{ean13.strip()}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "DewHomeAssistantES/1.0 (Local-First)"})
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

        if data.get("status") != 1 or "product" not in data:
            return None

        p = data["product"]
        name = p.get("product_name_es") or p.get("product_name") or f"Producto {ean13}"
        brand = p.get("brands", "")
        allergens_tags = [
            str(t).replace("en:", "").replace("es:", "") for t in p.get("allergens_tags", [])
        ]
        ingredients_text = p.get("ingredients_text_es") or p.get("ingredients_text") or ""

        return self.upsert_custom_barcode_product(
            ean13=ean13,
            product_name=name,
            brand=brand,
            category="alimentacion",
            default_unit=p.get("quantity", "unidades") or "unidades",
            allergens=allergens_tags,
            ingredients_text=ingredients_text,
            source="openfoodfacts_es",
        )
