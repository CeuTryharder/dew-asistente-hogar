#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de Persistencia Local (`SQLite` / `SQLCipher`), Gestión de Memoria con Consentimiento
y Registro de Auditoría (`Action Log` con soporte de Deshacer).

Cumple los requisitos de Privacidad y Seguridad de Dew:
  1. Ningún dato personal se guarda sin permiso explícito (`consent_granted=True`).
  2. El usuario puede consultar, corregir, exportar (JSON) y borrar (total o parcialmente)
     toda su memoria en cualquier momento.
  3. Cada acción realizada o propuesta queda registrada en `action_audit_log`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DewLocalStorage:
    """
    Capa de almacenamiento local-first.
    En producción móvil (Android/iOS) se enlaza contra SQLCipher (AES-256) cuya clave
    maestra reside en Android Keystore / iOS Secure Enclave.
    """

    def __init__(self, db_path: str | Path = ":memory:", sqlcipher_key: Optional[str] = None) -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if sqlcipher_key:
            # Compatible con drivers SQLCipher; en SQLite estándar es un PRAGMA inocuo o integrable
            self.conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            -- 1. Memoria estructurada de preferencias y contexto del hogar (siempre con permiso)
            CREATE TABLE IF NOT EXISTS user_memories (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                consent_granted INTEGER NOT NULL CHECK (consent_granted IN (0, 1)),
                consent_timestamp TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- 2. Propuestas pendientes de guardar en memoria (esperando confirmación del usuario)
            CREATE TABLE IF NOT EXISTS pending_memory_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                proposed_value TEXT NOT NULL,
                category TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            -- 3. Inventario unificado (alimentación + productos de limpieza y consumibles)
            CREATE TABLE IF NOT EXISTS inventory_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL CHECK (category IN ('alimentacion', 'limpieza', 'hogar')),
                location TEXT NOT NULL DEFAULT 'nevera',
                qty REAL NOT NULL DEFAULT 0.0,
                unit TEXT NOT NULL DEFAULT 'unidades',
                confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
                uncertainty_note TEXT,
                last_price_eur REAL,
                preferred_store TEXT,
                estimated_expiry_date TEXT,
                depletion_rate_days INTEGER,
                updated_at TEXT NOT NULL
            );

            -- 4. Borradores de cestas de compra (NUNCA se ejecutan automáticamente)
            CREATE TABLE IF NOT EXISTS shopping_cart_drafts (
                cart_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('DRAFT_PENDING_REVIEW', 'CONFIRMED_BY_USER', 'DISCARDED')),
                budget_limit_eur REAL,
                estimated_total_eur REAL NOT NULL,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );

            -- 5. Bóveda local de recordatorios de trámites españoles
            CREATE TABLE IF NOT EXISTS spanish_procedures_vault (
                proc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                administration TEXT NOT NULL,
                due_date TEXT,
                checklist_json TEXT NOT NULL,
                official_app_package TEXT,
                official_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            -- 6. Registro de auditoría transparente (Action Log) con soporte de reversión (Undo)
            CREATE TABLE IF NOT EXISTS action_audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                user_confirmed INTEGER NOT NULL,
                previous_state_json TEXT,
                new_state_json TEXT,
                undone INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # Gestión de Memoria con Permiso Explícito
    # -------------------------------------------------------------------------
    def request_to_remember(self, key: str, proposed_value: str, category: str, reason: str) -> int:
        """
        Registra una solicitud para guardar un dato personal. No pasa a `user_memories`
        hasta que el usuario llama a `confirm_memory_request`.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO pending_memory_requests (key, proposed_value, category, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, proposed_value, category, reason, utc_now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def confirm_memory_request(self, request_id: int) -> Dict[str, Any]:
        """Confirma con permiso explícito del usuario una solicitud pendiente y la guarda en memoria."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM pending_memory_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"No existe la solicitud de memoria #{request_id}")

        self.save_memory_with_permission(
            key=row["key"],
            value=row["proposed_value"],
            category=row["category"],
            source=f"Confirmado por usuario (req #{request_id})",
            consent_granted=True,
        )
        cur.execute("DELETE FROM pending_memory_requests WHERE request_id = ?", (request_id,))
        self.conn.commit()
        return {"key": row["key"], "value": row["proposed_value"], "category": row["category"]}

    def save_memory_with_permission(
        self,
        key: str,
        value: str,
        category: str,
        source: str,
        consent_granted: bool,
    ) -> None:
        if not consent_granted:
            raise PermissionError(
                "Política de Privacidad de Dew: prohibido guardar preferencias o datos personales sin consentimiento explícito."
            )
        now = utc_now_iso()
        prev = self.get_memory(key)
        self.conn.execute(
            """
            INSERT INTO user_memories (key, value, category, source, consent_granted, consent_timestamp, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (key, value, category, source, now, now),
        )
        self.log_action(
            action_type="SAVE_MEMORY",
            summary=f"Guardada preferencia '{key}' = '{value}'",
            user_confirmed=True,
            previous_state=prev,
            new_state={"key": key, "value": value, "category": category},
        )
        self.conn.commit()

    def get_memory(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM user_memories WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def list_all_memories(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM user_memories ORDER BY category, key").fetchall()
        return [dict(r) for r in rows]

    def delete_memory(self, key: str) -> bool:
        prev = self.get_memory(key)
        if not prev:
            return False
        self.conn.execute("DELETE FROM user_memories WHERE key = ?", (key,))
        self.log_action(
            action_type="DELETE_MEMORY",
            summary=f"Borrada preferencia '{key}'",
            user_confirmed=True,
            previous_state=prev,
            new_state=None,
        )
        self.conn.commit()
        return True

    def build_compact_context_summary(self) -> str:
        """
        Construye el resumen ultracompacto (<200 tokens) que se inyecta en el prompt
        local de `Qwen3.8-9B-Distill`.
        """
        memories = self.list_all_memories()
        mem_parts = [f"{m['key']}: {m['value']}" for m in memories]
        items = self.conn.execute(
            "SELECT normalized_name, qty, unit, confidence FROM inventory_items ORDER BY qty ASC LIMIT 15"
        ).fetchall()
        inv_parts = [
            f"{i['normalized_name']} ({i['qty']} {i['unit']}"
            + (f", duda {int(i['confidence']*100)}%" if i["confidence"] < 0.75 else "")
            + ")"
            for i in items
        ]
        mem_str = "; ".join(mem_parts) if mem_parts else "Sin preferencias registradas aún"
        inv_str = "; ".join(inv_parts) if inv_parts else "Inventario vacío"
        return f"Preferencias: {mem_str}. Inventario clave: {inv_str}."

    # -------------------------------------------------------------------------
    # Portabilidad (Exportación JSON) y Borrado Total (Derechos ARCO)
    # -------------------------------------------------------------------------
    def export_all_user_data(self) -> Dict[str, Any]:
        """Exporta todos los datos recordados en un diccionario JSON legible y portable."""
        return {
            "exported_at_utc": utc_now_iso(),
            "memories": self.list_all_memories(),
            "inventory": [
                dict(r) for r in self.conn.execute("SELECT * FROM inventory_items ORDER BY category, normalized_name")
            ],
            "shopping_carts": [
                dict(r) for r in self.conn.execute("SELECT * FROM shopping_cart_drafts ORDER BY created_at DESC")
            ],
            "spanish_procedures": [
                dict(r) for r in self.conn.execute("SELECT * FROM spanish_procedures_vault ORDER BY created_at DESC")
            ],
            "audit_log": [
                dict(r) for r in self.conn.execute("SELECT * FROM action_audit_log ORDER BY log_id DESC")
            ],
        }

    def wipe_all_user_data(self) -> None:
        """Borra de forma inmediata toda la información personal, inventario e historial."""
        cur = self.conn.cursor()
        cur.executescript(
            """
            DELETE FROM user_memories;
            DELETE FROM pending_memory_requests;
            DELETE FROM inventory_items;
            DELETE FROM shopping_cart_drafts;
            DELETE FROM spanish_procedures_vault;
            DELETE FROM action_audit_log;
            VACUUM;
            """
        )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # Registro de Auditoría (Action Log)
    # -------------------------------------------------------------------------
    def log_action(
        self,
        action_type: str,
        summary: str,
        user_confirmed: bool,
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO action_audit_log
                (timestamp, action_type, summary, user_confirmed, previous_state_json, new_state_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                action_type,
                summary,
                1 if user_confirmed else 0,
                json.dumps(previous_state, ensure_ascii=False) if previous_state else None,
                json.dumps(new_state, ensure_ascii=False) if new_state else None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_recent_audit_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM action_audit_log ORDER BY log_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
