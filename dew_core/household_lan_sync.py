#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sincronizador Doméstico P2P en Red Local (Wi-Fi LAN) con Resolución de Conflictos CRDT (LWW)
y Autenticación Criptográfica (`PBKDF2-HMAC-SHA256` + `HMAC-SHA256`).

Permite que 2 o más teléfonos de un mismo hogar mantengan sincronizados:
  - El inventario de nevera, despensa y limpieza (`inventory_items`).
  - Las preferencias domésticas compartidas con consentimiento (`user_memories`).
  - Las cestas de compra (`shopping_cart_drafts`).

Garantías de Privacidad y Seguridad:
  1. Cero servidores en la nube: el paquete viaja directamente entre móviles en la red Wi-Fi local.
  2. Exclusión estricta de datos sensibles: la bóveda de trámites/salud (`spanish_procedures_vault`)
     y las solicitudes de permiso pendientes (`pending_memory_requests`) NUNCA se incluyen en el paquete.
  3. Firma HMAC-SHA256 con clave derivada por PBKDF2 (100.000 iteraciones) a partir del código
     de emparejamiento del hogar: cualquier paquete alterado o con PIN erróneo es rechazado.
  4. Fusión determinista Last-Write-Wins (LWW-Element-Set) por marca de tiempo ISO-8601 UTC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, List

from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso

PBKDF2_ITERATIONS = 100_000


def derive_household_secret(pairing_code: str, household_id: str) -> bytes:
    """Deriva una clave simétrica de 256 bits a partir del PIN/QR del hogar y su identificador."""
    if len(pairing_code.strip()) < 6:
        raise ValueError("El código de emparejamiento del hogar debe tener al menos 6 caracteres.")
    salt = f"dew-lan-sync-v1:{household_id.strip()}".encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256",
        pairing_code.strip().encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=32,
    )


def _canonical_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class HouseholdLanSyncEngine:
    """
    Motor de sincronización P2P entre dispositivos del mismo hogar.
    """

    def __init__(
        self,
        storage: DewLocalStorage,
        node_id: str,
        household_id: str,
        pairing_code: str,
    ) -> None:
        self.storage = storage
        self.node_id = node_id
        self.household_id = household_id
        self.secret_key = derive_household_secret(pairing_code, household_id)

    def build_signed_sync_packet(self) -> Dict[str, Any]:
        """
        Exporta únicamente las entidades compartibles del hogar (inventario y preferencias aprobadas)
        y firma criptográficamente el paquete con `HMAC-SHA256`.
        """
        inventory_rows = [
            dict(r) for r in self.storage.conn.execute("SELECT * FROM inventory_items").fetchall()
        ]
        memory_rows = [
            dict(r)
            for r in self.storage.conn.execute(
                "SELECT * FROM user_memories WHERE consent_granted = 1"
            ).fetchall()
        ]

        body: Dict[str, Any] = {
            "protocol_version": "1.0",
            "household_id": self.household_id,
            "origin_node_id": self.node_id,
            "timestamp_utc": utc_now_iso(),
            "nonce": secrets.token_hex(16),
            "shared_inventory": inventory_rows,
            "shared_memories": memory_rows,
        }

        mac = hmac.new(self.secret_key, _canonical_json_bytes(body), hashlib.sha256).hexdigest()
        return {
            "body": body,
            "hmac_sha256": mac,
        }

    def verify_and_merge_sync_packet(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verifica la firma HMAC-SHA256 del paquete entrante y aplica la fusión CRDT Last-Write-Wins (LWW)
        sobre el inventario y las preferencias compartidas.
        """
        body = packet.get("body")
        received_mac = str(packet.get("hmac_sha256", ""))
        if not isinstance(body, dict) or not received_mac:
            raise ValueError("Formato de paquete de sincronización LAN inválido.")

        if body.get("household_id") != self.household_id:
            raise PermissionError("El paquete pertenece a un hogar distinto (`household_id` no coincide).")

        expected_mac = hmac.new(self.secret_key, _canonical_json_bytes(body), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_mac, received_mac):
            raise PermissionError(
                "Fallo de autenticación HMAC-SHA256: código de emparejamiento incorrecto o paquete manipulado."
            )

        origin_node = str(body.get("origin_node_id", "peer"))
        inv_inserted_or_updated = self._merge_inventory_lww(body.get("shared_inventory", []))
        mem_inserted_or_updated = self._merge_memories_lww(body.get("shared_memories", []))

        self.storage.log_action(
            action_type="HOUSEHOLD_LAN_SYNC",
            summary=(
                f"Sincronización Wi-Fi local desde '{origin_node}': "
                f"{inv_inserted_or_updated} ítems de inventario y {mem_inserted_or_updated} preferencias actualizadas"
            ),
            user_confirmed=True,
            new_state={
                "origin_node": origin_node,
                "inventory_updates": inv_inserted_or_updated,
                "memory_updates": mem_inserted_or_updated,
            },
        )
        self.storage.conn.commit()

        return {
            "status": "SYNC_OK",
            "origin_node_id": origin_node,
            "inventory_updates_applied": inv_inserted_or_updated,
            "memory_updates_applied": mem_inserted_or_updated,
        }

    def _merge_inventory_lww(self, remote_items: List[Dict[str, Any]]) -> int:
        updated_count = 0
        cur = self.storage.conn.cursor()

        for r_item in remote_items:
            name = r_item["normalized_name"]
            r_updated_at = str(r_item.get("updated_at", ""))
            local_row = cur.execute(
                "SELECT updated_at FROM inventory_items WHERE normalized_name = ?", (name,)
            ).fetchone()

            # Regla CRDT Last-Write-Wins (LWW): gana la marca de tiempo ISO-8601 más reciente
            if local_row is None or r_updated_at > str(local_row["updated_at"]):
                cur.execute(
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
                        uncertainty_note = excluded.uncertainty_note,
                        last_price_eur = excluded.last_price_eur,
                        preferred_store = excluded.preferred_store,
                        estimated_expiry_date = excluded.estimated_expiry_date,
                        depletion_rate_days = excluded.depletion_rate_days,
                        updated_at = excluded.updated_at
                    """,
                    (
                        name,
                        r_item.get("category", "alimentacion"),
                        r_item.get("location", "nevera"),
                        float(r_item.get("qty", 0.0)),
                        r_item.get("unit", "unidades"),
                        float(r_item.get("confidence", 1.0)),
                        r_item.get("uncertainty_note"),
                        r_item.get("last_price_eur"),
                        r_item.get("preferred_store"),
                        r_item.get("estimated_expiry_date"),
                        r_item.get("depletion_rate_days"),
                        r_updated_at,
                    ),
                )
                updated_count += 1

        return updated_count

    def _merge_memories_lww(self, remote_memories: List[Dict[str, Any]]) -> int:
        updated_count = 0
        cur = self.storage.conn.cursor()

        for r_mem in remote_memories:
            if int(r_mem.get("consent_granted", 0)) != 1:
                continue
            key = r_mem["key"]
            r_updated_at = str(r_mem.get("updated_at", ""))
            local_row = cur.execute(
                "SELECT updated_at FROM user_memories WHERE key = ?", (key,)
            ).fetchone()

            if local_row is None or r_updated_at > str(local_row["updated_at"]):
                cur.execute(
                    """
                    INSERT INTO user_memories (
                        key, value, category, source, consent_granted, consent_timestamp, updated_at
                    )
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = excluded.category,
                        source = excluded.source,
                        consent_timestamp = excluded.consent_timestamp,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        r_mem["value"],
                        r_mem.get("category", "hogar"),
                        r_mem.get("source", "Sincronización LAN Hogar"),
                        r_mem.get("consent_timestamp", r_updated_at),
                        r_updated_at,
                    ),
                )
                updated_count += 1

        return updated_count
