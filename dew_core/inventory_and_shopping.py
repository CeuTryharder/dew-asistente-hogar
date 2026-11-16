#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de Inventario Doméstico (Nevera, Despensa y Productos de Limpieza) y Cestas de Compra.
Implementa:
  1. Registro de alimentos y consumibles de limpieza con nivel de confianza (`confidence`)
     para gestionar la incertidumbre en fotos de nevera.
  2. Alertas tempranas de agotamiento y caducidad.
  3. Generación de borradores de cesta de compra (`DRAFT_PENDING_REVIEW`) con coste estimado.
     Jamás ejecuta una compra automática sin confirmación explícita del usuario.
  4. Guardarraíl determinista de seguridad química en rutinas de limpieza.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso
from model_pipeline.grammars.safety_and_schema_validator import detect_chemical_hazard

UNCERTAINTY_THRESHOLD = 0.70


class InventoryAndShoppingEngine:
    def __init__(self, storage: DewLocalStorage) -> None:
        self.storage = storage

    def upsert_inventory_item(
        self,
        normalized_name: str,
        category: str,
        qty: float,
        unit: str = "unidades",
        location: str = "nevera",
        confidence: float = 1.0,
        uncertainty_note: Optional[str] = None,
        last_price_eur: Optional[float] = None,
        preferred_store: Optional[str] = None,
        expiry_in_days: Optional[int] = None,
        depletion_rate_days: Optional[int] = None,
        user_confirmed: bool = True,
    ) -> Dict[str, Any]:
        if category not in ("alimentacion", "limpieza", "hogar"):
            raise ValueError(f"Categoría inválida: {category}")

        expiry_iso: Optional[str] = None
        if expiry_in_days is not None:
            expiry_iso = (datetime.now(timezone.utc) + timedelta(days=expiry_in_days)).date().isoformat()

        now = utc_now_iso()
        self.storage.conn.execute(
            """
            INSERT INTO inventory_items (
                normalized_name, category, location, qty, unit, confidence,
                uncertainty_note, last_price_eur, preferred_store,
                estimated_expiry_date, depletion_rate_days, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                category = excluded.category,
                location = excluded.location,
                qty = excluded.qty,
                unit = excluded.unit,
                confidence = excluded.confidence,
                uncertainty_note = COALESCE(excluded.uncertainty_note, inventory_items.uncertainty_note),
                last_price_eur = COALESCE(excluded.last_price_eur, inventory_items.last_price_eur),
                preferred_store = COALESCE(excluded.preferred_store, inventory_items.preferred_store),
                estimated_expiry_date = COALESCE(excluded.estimated_expiry_date, inventory_items.estimated_expiry_date),
                depletion_rate_days = COALESCE(excluded.depletion_rate_days, inventory_items.depletion_rate_days),
                updated_at = excluded.updated_at
            """,
            (
                normalized_name,
                category,
                location,
                qty,
                unit,
                confidence,
                uncertainty_note,
                last_price_eur,
                preferred_store,
                expiry_iso,
                depletion_rate_days,
                now,
            ),
        )
        self.storage.log_action(
            action_type="UPSERT_INVENTORY",
            summary=f"Inventario actualizado: {normalized_name} ({qty} {unit}, confianza {int(confidence*100)}%)",
            user_confirmed=user_confirmed,
            new_state={"name": normalized_name, "qty": qty, "unit": unit, "confidence": confidence},
        )
        self.storage.conn.commit()
        return self.get_item(normalized_name)  # type: ignore[return-value]

    def get_item(self, normalized_name: str) -> Optional[Dict[str, Any]]:
        row = self.storage.conn.execute(
            "SELECT * FROM inventory_items WHERE normalized_name = ?", (normalized_name,)
        ).fetchone()
        return dict(row) if row else None

    def process_fridge_photo_detections(
        self, detections: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Procesa una lista de detecciones visuales de una foto de nevera o despensa.
        Separa automáticamente:
          - `high_confidence_updated`: ítems con confianza >= 0.70 que se actualizan.
          - `uncertain_questions`: ítems dudosos (< 0.70) sobre los que Dew pregunta al usuario
            en lugar de presentar suposiciones como hechos.
        """
        high_conf: List[Dict[str, Any]] = []
        uncertain: List[Dict[str, Any]] = []

        for det in detections:
            conf = float(det.get("confidence", 0.5))
            name = det["name"]
            qty = float(det.get("qty", 1.0))
            unit = det.get("unit", "unidades")
            note = det.get("note")

            if conf >= UNCERTAINTY_THRESHOLD:
                updated = self.upsert_inventory_item(
                    normalized_name=name,
                    category=det.get("category", "alimentacion"),
                    qty=qty,
                    unit=unit,
                    location=det.get("location", "nevera"),
                    confidence=conf,
                    uncertainty_note=note,
                    user_confirmed=False,
                )
                high_conf.append(updated)
            else:
                uncertain.append({
                    "detected_label": name,
                    "estimated_qty": qty,
                    "unit": unit,
                    "confidence": conf,
                    "question_for_user": (
                        f"He visto algo parecido a '{name}' con solo un {int(conf*100)}% de seguridad"
                        + (f" ({note})" if note else "")
                        + ". ¿Me confirmas qué es y cuánto queda?"
                    ),
                })

        return {
            "high_confidence_updated": high_conf,
            "uncertain_questions": uncertain,
        }

    def get_low_stock_and_expiring_alerts(self, within_days: int = 3) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detecta alimentos próximos a caducar y productos de alimentación o limpieza
        que están a punto de agotarse (`qty <= 1.0` o `qty <= 0.2` en porcentaje/litros).
        """
        cutoff_date = (datetime.now(timezone.utc) + timedelta(days=within_days)).date().isoformat()
        expiring_rows = self.storage.conn.execute(
            """
            SELECT * FROM inventory_items
            WHERE estimated_expiry_date IS NOT NULL
              AND estimated_expiry_date <= ?
              AND qty > 0
            ORDER BY estimated_expiry_date ASC
            """,
            (cutoff_date,),
        ).fetchall()

        low_stock_rows = self.storage.conn.execute(
            """
            SELECT * FROM inventory_items
            WHERE qty <= 0.25 OR (unit IN ('unidades', 'pastillas', 'rollos') AND qty <= 2)
            ORDER BY category, qty ASC
            """
        ).fetchall()

        return {
            "expiring_soon": [dict(r) for r in expiring_rows],
            "low_stock": [dict(r) for r in low_stock_rows],
        }

    def create_shopping_cart_draft(
        self,
        store: str,
        items: List[Dict[str, Any]],
        budget_limit_eur: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Crea una cesta de compra en estado `DRAFT_PENDING_REVIEW`.
        NUNCA ejecuta una compra real: requiere revisión y confirmación expresa del usuario.
        """
        total_eur = round(
            sum(float(i.get("est_price_eur", 0.0)) * float(i.get("qty", 1.0)) for i in items),
            2,
        )
        now = utc_now_iso()
        cur = self.storage.conn.cursor()
        cur.execute(
            """
            INSERT INTO shopping_cart_drafts
                (store, status, budget_limit_eur, estimated_total_eur, items_json, created_at)
            VALUES (?, 'DRAFT_PENDING_REVIEW', ?, ?, ?, ?)
            """,
            (store, budget_limit_eur, total_eur, json.dumps(items, ensure_ascii=False), now),
        )
        cart_id = int(cur.lastrowid)
        self.storage.log_action(
            action_type="PROPOSE_CART_DRAFT",
            summary=f"Propuesta de cesta #{cart_id} en {store} por {total_eur:.2f} € (Pendiente de confirmación)",
            user_confirmed=False,
            new_state={"cart_id": cart_id, "store": store, "estimated_total_eur": total_eur},
        )
        self.storage.conn.commit()

        within_budget = True if budget_limit_eur is None else (total_eur <= budget_limit_eur)
        return {
            "cart_id": cart_id,
            "store": store,
            "status": "DRAFT_PENDING_REVIEW",
            "estimated_total_eur": total_eur,
            "budget_limit_eur": budget_limit_eur,
            "within_budget": within_budget,
            "requires_user_confirmation": True,
            "items": items,
        }

    def confirm_shopping_cart(self, cart_id: int) -> Dict[str, Any]:
        """Marca la cesta como revisada y aprobada por el usuario para usarla en tienda o web oficial."""
        now = utc_now_iso()
        row = self.storage.conn.execute(
            "SELECT * FROM shopping_cart_drafts WHERE cart_id = ?", (cart_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"No existe la cesta #{cart_id}")

        self.storage.conn.execute(
            "UPDATE shopping_cart_drafts SET status = 'CONFIRMED_BY_USER', confirmed_at = ? WHERE cart_id = ?",
            (now, cart_id),
        )
        self.storage.log_action(
            action_type="CONFIRM_SHOPPING_CART",
            summary=f"Cesta #{cart_id} confirmada por el usuario ({row['estimated_total_eur']:.2f} €)",
            user_confirmed=True,
        )
        self.storage.conn.commit()
        return {
            "cart_id": cart_id,
            "status": "CONFIRMED_BY_USER",
            "confirmed_at": now,
            "estimated_total_eur": row["estimated_total_eur"],
        }

    @staticmethod
    def validate_cleaning_advice_safety(advice_text: str) -> Dict[str, Any]:
        """Verifica que una rutina o consejo de limpieza no sugiera mezclar químicos incompatibles."""
        hazard = detect_chemical_hazard(advice_text)
        if hazard:
            return {
                "safe": False,
                "hazard": hazard,
                "safe_replacement_message": (
                    "ALERTA DE SEGURIDAD DOMÉSTICA: Nunca mezcles lejía con amoniaco, vinagre, antical ni alcohol. "
                    "La reacción libera gases altamente tóxicos (cloraminas o gas cloro). Usa únicamente un producto "
                    "cada vez y aclara con abundante agua."
                ),
            }
        return {"safe": True, "hazard": None}
