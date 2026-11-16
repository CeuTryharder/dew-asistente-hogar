#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selector Adaptativo de Modelo por Hardware (`HardwareModelSelector`),
Gestor Secuencial de Memoria RAM (`SequentialMemoryManager`) y Orquestador Principal de Dew.

Gestiona los dos perfiles oficiales de `empero-ai/Qwen3.8-9B-Distill`:
  - `DEW_9B_COMPACT_8GB` (`IQ3_XXS` + `imatrix` en español, ~3,75 GB) para móviles de 8 GB RAM.
  - `DEW_9B_PRO_12GB` (`Q4_K_M` + `imatrix` en español, ~5,3 GB) para móviles de 12 GB+ RAM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from dew_core.barcode_and_allergens import BarcodeAndAllergenService
from dew_core.domotics_and_spanish_services import HomeAssistantLocalConnector, SpanishServicesCopilot
from dew_core.inventory_and_shopping import InventoryAndShoppingEngine
from dew_core.local_rag_fts import LocalHouseholdHistorySearch
from dew_core.meal_planner import FlexibleMealPlanner
from dew_core.storage_and_memory import DewLocalStorage
from model_pipeline.grammars.safety_and_schema_validator import validate_dew_response
from model_pipeline.prompts.dew_prompt_builder import BuiltPrompt, build_qwen38_prompt


@dataclass
class SelectedModelTier:
    tier_id: str
    gguf_filename: str
    quantization: str
    estimated_ram_mb: int
    sequential_unload_required: bool
    llama_cpp_flags: Dict[str, Any]


class HardwareModelSelector:
    """
    Selecciona automáticamente la variante de `empero-ai/Qwen3.8-9B-Distill`
    según la memoria RAM física total del dispositivo móvil.
    """

    @staticmethod
    def select_tier_for_device(total_ram_gb: float) -> SelectedModelTier:
        if total_ram_gb >= 11.5:
            is_16gb_flagship = total_ram_gb >= 15.0
            return SelectedModelTier(
                tier_id="DEW_9B_PRO_12GB",
                gguf_filename="dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf",
                quantization=(
                    "Q4_K_M (imatrix-ES, embd q5_k, out q6_k · 16GB Tablet Turbo 8K ctx)"
                    if is_16gb_flagship
                    else "Q4_K_M (imatrix-ES, embd q5_k, out q6_k)"
                ),
                estimated_ram_mb=6450 if is_16gb_flagship else 6100,
                sequential_unload_required=False,
                llama_cpp_flags={
                    "n_ctx": 8192 if is_16gb_flagship else 4096,
                    "type_k": "q8_0",
                    "type_v": "q8_0" if is_16gb_flagship else "q4_0",
                    "use_mmap": True,
                    "use_mlock": False,
                    "flash_attn": True,
                    "n_gpu_layers": 99,
                    "n_batch": 1024 if is_16gb_flagship else 512,
                },
            )
        elif total_ram_gb >= 7.4:
            return SelectedModelTier(
                tier_id="DEW_9B_COMPACT_8GB",
                gguf_filename="dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf",
                quantization="IQ3_XXS (imatrix-ES, embd q4_k, out q5_k)",
                estimated_ram_mb=4350,
                sequential_unload_required=True,
                llama_cpp_flags={
                    "n_ctx": 4096,
                    "type_k": "q8_0",
                    "type_v": "q4_0",
                    "use_mmap": True,
                    "use_mlock": False,
                    "flash_attn": True,
                },
            )
        else:
            raise EnvironmentError(
                f"Dispositivo con {total_ram_gb:.1f} GB de RAM: las ediciones de 9B requieren un mínimo "
                "de 8 GB de RAM física. Para terminales de 4-6 GB debe activarse el perfil de rescate ultraligero."
            )


class SequentialMemoryManager:
    """
    Controla qué modelo está residente en RAM activa en teléfonos de 8 GB
    para evitar que el Low Memory Killer (LMKD) de Android cierre la aplicación.
    """

    def __init__(self, sequential_required: bool) -> None:
        self.sequential_required = sequential_required
        self.active_modules: List[str] = []
        self.transition_history: List[str] = []

    def activate_module(self, module_name: str) -> None:
        if self.sequential_required:
            # Descarga módulos pesados previos antes de activar el siguiente
            if self.active_modules:
                unloaded = list(self.active_modules)
                self.active_modules.clear()
                self.transition_history.append(f"UNLOAD({','.join(unloaded)}) -> LOAD({module_name})")
            else:
                self.transition_history.append(f"LOAD({module_name})")
            self.active_modules = [module_name]
        else:
            if module_name not in self.active_modules:
                self.active_modules.append(module_name)
            self.transition_history.append(f"KEEP_CONCURRENT({','.join(self.active_modules)})")


class DewAssistantOrchestrator:
    """
    Orquestador de alto nivel que une almacenamiento cifrado, inventario, domótica,
    trámites españoles, construcción de prompts con switch `<think>` y validación de seguridad.
    """

    def __init__(self, device_ram_gb: float = 8.0, db_path: str = ":memory:") -> None:
        self.tier = HardwareModelSelector.select_tier_for_device(device_ram_gb)
        self.memory_mgr = SequentialMemoryManager(self.tier.sequential_unload_required)
        self.storage = DewLocalStorage(db_path=db_path)
        self.inventory = InventoryAndShoppingEngine(self.storage)
        self.meal_planner = FlexibleMealPlanner(self.storage, self.inventory)
        self.barcode_service = BarcodeAndAllergenService(self.storage, self.inventory)
        self.history_search = LocalHouseholdHistorySearch(self.storage)
        self.domotics = HomeAssistantLocalConnector(self.storage)
        self.spanish_services = SpanishServicesCopilot(self.storage)

    def prepare_voice_turn(self, user_utterance: str) -> BuiltPrompt:
        """
        Simula el ciclo completo de entrada por voz:
        1. Activa STT (Whisper INT8)
        2. Transcribe y descarga buffers de audio (en móviles de 8 GB)
        3. Construye el prompt con contexto local e interruptor `<think>`
        4. Activa el motor 9B
        """
        self.memory_mgr.activate_module("STT_WHISPER_BASE_INT8")
        context_summary = self.storage.build_compact_context_summary()
        built_prompt = build_qwen38_prompt(user_utterance, context_summary)
        self.memory_mgr.activate_module(f"LLM_{self.tier.tier_id}")
        return built_prompt

    def validate_and_finalize_turn(self, model_raw_output: str | Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida la salida del modelo 9B con el motor determinista (`CHEM_GUARD`, esquemas y
        confirmaciones obligatorias) y prepara la síntesis de voz (`Piper TTS`).
        """
        validation = validate_dew_response(model_raw_output)
        self.memory_mgr.activate_module("TTS_PIPER_ES")
        return {
            "tier_used": self.tier.tier_id,
            "is_valid": validation.is_valid,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "sanitized_output": validation.sanitized_output,
            "memory_transitions": list(self.memory_mgr.transition_history),
        }
