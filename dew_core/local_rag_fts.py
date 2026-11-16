#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Buscador Histórico Local (RAG Ligero con `SQLite FTS5`) y Analítica Flexible de Precios y Gastos.

Permite al usuario sin conexión a internet:
  1. Consultar dónde compró más barato cualquier producto entre sus tiendas habituales
     (supermercados, frutería de barrio, mercado, etc.) y ver la evolución del precio.
  2. Analizar su gasto acumulado por categoría (`alimentacion`, `limpieza`, `hogar`) y por tienda,
     comparándolo contra el objetivo de presupuesto mensual o semanal que el propio usuario elija.
  3. Buscar en <3 ms sobre notas domésticas, recetas caseras, garantías o tickets antiguos
     mediante búsqueda de texto completo (`SQLite FTS5` con ranking BM25) para inyectar solo los
     fragmentos relevantes en la ventana de 4.096 tokens de `Qwen3.8-9B-Distill`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso


class LocalHouseholdHistorySearch:
    def __init__(self, storage: DewLocalStorage) -> None:
        self.storage = storage
        self._fts5_supported = True
        self._init_history_and_fts_tables()

    def _init_history_and_fts_tables(self) -> None:
        cur = self.storage.conn.cursor()
        cur.executescript(
            """
            -- 1. Histórico de compras por línea (para comparar precios entre tiendas y medir gasto)
            CREATE TABLE IF NOT EXISTS purchase_price_history (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'alimentacion',
                store TEXT NOT NULL,
                qty REAL NOT NULL DEFAULT 1.0,
                unit TEXT NOT NULL DEFAULT 'unidades',
                unit_price_eur REAL NOT NULL,
                total_price_eur REAL NOT NULL,
                purchased_at TEXT NOT NULL
            );

            -- 2. Notas, trucos caseros, manuales y documentos del hogar
            CREATE TABLE IF NOT EXISTS household_notes (
                note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'hogar',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS household_knowledge_fts
                USING fts5(doc_type, ref_id, title, body);
                """
            )
        except Exception:
            self._fts5_supported = False
        self.storage.conn.commit()

    def record_purchase_item(
        self,
        product_name: str,
        store: str,
        unit_price_eur: float,
        qty: float = 1.0,
        unit: str = "unidades",
        category: str = "alimentacion",
        purchased_at: Optional[str] = None,
    ) -> int:
        ts = purchased_at or utc_now_iso()
        total_eur = round(float(unit_price_eur) * float(qty), 2)
        cur = self.storage.conn.cursor()
        cur.execute(
            """
            INSERT INTO purchase_price_history
                (product_name, category, store, qty, unit, unit_price_eur, total_price_eur, purchased_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_name.strip(), category, store.strip(), qty, unit, float(unit_price_eur), total_eur, ts),
        )
        entry_id = int(cur.lastrowid)

        if self._fts5_supported:
            cur.execute(
                "INSERT INTO household_knowledge_fts (doc_type, ref_id, title, body) VALUES (?, ?, ?, ?)",
                (
                    "purchase",
                    str(entry_id),
                    product_name.strip(),
                    f"{product_name} comprado en {store} a {unit_price_eur:.2f} €/{unit} (total {total_eur:.2f} €) [{category}]",
                ),
            )
        self.storage.conn.commit()
        return entry_id

    def add_household_note(self, title: str, content: str, category: str = "hogar") -> int:
        now = utc_now_iso()
        cur = self.storage.conn.cursor()
        cur.execute(
            "INSERT INTO household_notes (title, category, content, created_at) VALUES (?, ?, ?, ?)",
            (title.strip(), category.strip(), content.strip(), now),
        )
        note_id = int(cur.lastrowid)
        if self._fts5_supported:
            cur.execute(
                "INSERT INTO household_knowledge_fts (doc_type, ref_id, title, body) VALUES (?, ?, ?, ?)",
                ("note", str(note_id), title.strip(), f"{title}: {content} [{category}]"),
            )
        self.storage.conn.commit()
        return note_id

    def compare_product_prices_across_stores(self, product_query: str) -> Dict[str, Any]:
        """
        Busca en todas las compras registradas del usuario dónde ha comprado más barato
        un producto (ej. 'aceite de oliva', 'leche sin lactosa', 'detergente').
        """
        pattern = f"%{product_query.strip()}%"
        rows = self.storage.conn.execute(
            """
            SELECT product_name, store, unit_price_eur, unit, purchased_at
            FROM purchase_price_history
            WHERE product_name LIKE ?
            ORDER BY unit_price_eur ASC, purchased_at DESC
            """,
            (pattern,),
        ).fetchall()

        if not rows:
            return {
                "found": False,
                "query": product_query,
                "best_offer": None,
                "all_matches": [],
            }

        matches = [dict(r) for r in rows]
        return {
            "found": True,
            "query": product_query,
            "best_offer": matches[0],
            "highest_price": max(matches, key=lambda x: float(x["unit_price_eur"])),
            "potential_savings_per_unit_eur": round(
                float(max(matches, key=lambda x: float(x["unit_price_eur"]))["unit_price_eur"])
                - float(matches[0]["unit_price_eur"]),
                2,
            ),
            "all_matches": matches,
        }

    def get_flexible_spending_summary(
        self, custom_budget_limit_eur: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calcula el desglose de gasto acumulado por categoría y por tienda, y lo compara
        contra el presupuesto personalizado que el usuario indique (o el que tenga en memoria).
        """
        if custom_budget_limit_eur is None:
            mem = self.storage.get_memory("presupuesto_mensual_eur") or self.storage.get_memory("presupuesto_semanal_eur")
            if mem and mem.get("value"):
                try:
                    custom_budget_limit_eur = float(
                        str(mem["value"]).replace("€", "").replace(",", ".").split()[0]
                    )
                except ValueError:
                    custom_budget_limit_eur = None

        by_cat_rows = self.storage.conn.execute(
            """
            SELECT category, ROUND(SUM(total_price_eur), 2) AS total_eur, COUNT(*) AS items_count
            FROM purchase_price_history
            GROUP BY category
            ORDER BY total_eur DESC
            """
        ).fetchall()

        by_store_rows = self.storage.conn.execute(
            """
            SELECT store, ROUND(SUM(total_price_eur), 2) AS total_eur, COUNT(*) AS items_count
            FROM purchase_price_history
            GROUP BY store
            ORDER BY total_eur DESC
            """
        ).fetchall()

        total_spent = round(sum(float(r["total_eur"]) for r in by_cat_rows), 2)
        within_budget = True if custom_budget_limit_eur is None else (total_spent <= custom_budget_limit_eur)
        remaining = round(custom_budget_limit_eur - total_spent, 2) if custom_budget_limit_eur is not None else None

        return {
            "total_spent_eur": total_spent,
            "user_budget_limit_eur": custom_budget_limit_eur,
            "within_budget": within_budget,
            "remaining_budget_eur": remaining,
            "by_category": [dict(r) for r in by_cat_rows],
            "by_store": [dict(r) for r in by_store_rows],
        }

    def search_relevant_context_snippets(self, user_query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Recuperación de información (RAG local ligero) usando `SQLite FTS5` (o LIKE de respaldo)
        para inyectar solo los `top_k` recuerdos/tickets relevantes en el prompt del 9B.
        """
        tokens = [
            re.sub(r"[^\wáéíóúñÁÉÍÓÚÑ]", "", t).lower()
            for t in user_query.split()
            if len(t) >= 3
        ]
        if not tokens:
            return []

        if self._fts5_supported:
            fts_query = " OR ".join(f'"{t}"' for t in tokens[:6])
            try:
                rows = self.storage.conn.execute(
                    """
                    SELECT doc_type, ref_id, title, body
                    FROM household_knowledge_fts
                    WHERE household_knowledge_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, top_k),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:
                pass

        # Respaldo determinista si la consulta tiene caracteres especiales
        like_pattern = f"%{tokens[0]}%"
        note_rows = self.storage.conn.execute(
            "SELECT 'note' AS doc_type, note_id AS ref_id, title, content AS body FROM household_notes WHERE title LIKE ? OR content LIKE ? LIMIT ?",
            (like_pattern, like_pattern, top_k),
        ).fetchall()
        return [dict(r) for r in note_rows]
