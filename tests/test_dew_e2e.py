#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas de Extremo a Extremo (E2E) para Dew.
Valida:
  1. Selección adaptativa de `empero-ai/Qwen3.8-9B-Distill` (8 GB `IQ3_XXS` vs 12 GB+ `Q4_K_M`)
     y ciclo secuencial de memoria RAM.
  2. Memoria personal con permiso explícito (rechazo sin permiso, edición, exportación JSON y borrado total).
  3. Fotos de nevera con separación de confianza (>=70% actualizado vs <70% pregunta de incertidumbre).
  4. Cestas de compra en borrador (`DRAFT_PENDING_REVIEW`) que jamás compran automáticamente.
  5. Guardarraíl químico (`CHEM_GUARD`) ante mezclas peligrosas (lejía + amoniaco/vinagre).
  6. Control domótico local con exclusión de dispositivos protegidos (`protected=True`),
     fallos de conexión y confirmación obligatoria para cerraduras/alarmas.
  7. Preparación guiada de trámites españoles (`SERMAS`, `CatSalut`, `AEAT`, `Mi Carpeta Ciudadana`)
     con avisos legales y handoff al canal oficial.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest

from dew_core.domotics_and_spanish_services import SmartDeviceEntity
from dew_core.hardware_and_orchestrator import DewAssistantOrchestrator, HardwareModelSelector
from dew_core.household_lan_sync import HouseholdLanSyncEngine
from dew_core.meal_planner import HouseholdPlanningConfig, HouseholdRecipe, RecipeIngredient
from dew_core.model_downloader import DewModelDownloadManager
from dew_core.spanish_receipt_parser import parse_spanish_receipt_ocr
from dew_core.voice_pipeline import DewLocalVoiceEngine
from mobile_ui.app_server import handle_api_action
from model_pipeline.cloud_quantize_and_publish import (
    generate_huggingface_model_card,
    update_manifest_with_built_artifacts,
)
from pathlib import Path
import math


class TestDewEndToEnd(unittest.TestCase):

    def test_01_hardware_model_tier_selection_8gb_vs_12gb(self) -> None:
        # 1. Móvil de 8 GB de RAM -> Edición Compacta IQ3_XXS con descarga secuencial activa
        tier_8gb = HardwareModelSelector.select_tier_for_device(8.0)
        self.assertEqual(tier_8gb.tier_id, "DEW_9B_COMPACT_8GB")
        self.assertIn("iq3_xxs", tier_8gb.gguf_filename)
        self.assertTrue(tier_8gb.sequential_unload_required)
        self.assertEqual(tier_8gb.llama_cpp_flags["type_k"], "q8_0")
        self.assertEqual(tier_8gb.llama_cpp_flags["type_v"], "q4_0")

        # 2. Móvil de 12 GB de RAM -> Edición Pro Q4_K_M
        tier_12gb = HardwareModelSelector.select_tier_for_device(12.0)
        self.assertEqual(tier_12gb.tier_id, "DEW_9B_PRO_12GB")
        self.assertIn("q4_k_m", tier_12gb.gguf_filename)
        self.assertFalse(tier_12gb.sequential_unload_required)

    def test_02_memory_requires_explicit_consent_and_supports_export_and_wipe(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        # Intentar guardar sin permiso debe lanzar PermissionError
        with self.assertRaises(PermissionError):
            dew.storage.save_memory_with_permission(
                key="intolerancia",
                value="Sin lactosa",
                category="alimentacion",
                source="inferencia_no_autorizada",
                consent_granted=False,
            )

        # Flujo correcto: solicitar permiso -> confirmar por el usuario
        req_id = dew.storage.request_to_remember(
            key="intolerancia",
            proposed_value="Intolerancia a la lactosa (2 adultos)",
            category="alimentacion",
            reason="Mencionado por el usuario en la configuración inicial",
        )
        self.assertIsNone(dew.storage.get_memory("intolerancia"))

        dew.storage.confirm_memory_request(req_id)
        mem = dew.storage.get_memory("intolerancia")
        self.assertIsNotNone(mem)
        self.assertEqual(mem["value"], "Intolerancia a la lactosa (2 adultos)")

        # Exportar datos a JSON y luego borrar todo
        exported = dew.storage.export_all_user_data()
        self.assertEqual(len(exported["memories"]), 1)

        dew.storage.wipe_all_user_data()
        self.assertEqual(len(dew.storage.list_all_memories()), 0)

    def test_03_fridge_photo_uncertainty_and_shopping_cart_draft(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        # Detección de foto de nevera con 2 productos claros y 2 dudosos
        detections = [
            {"name": "Huevos camperos", "qty": 6, "unit": "unidades", "confidence": 0.94},
            {"name": "Leche sin lactosa", "qty": 0.2, "unit": "litros", "confidence": 0.89},
            {"name": "Táper opaco tapa azul", "qty": 1, "unit": "unidades", "confidence": 0.42, "note": "Interior no visible"},
            {"name": "Bote blanco al fondo", "qty": 1, "unit": "unidades", "confidence": 0.51, "note": "¿Queso fresco o yogur?"},
        ]
        result = dew.inventory.process_fridge_photo_detections(detections)
        self.assertEqual(len(result["high_confidence_updated"]), 2)
        self.assertEqual(len(result["uncertain_questions"]), 2)
        self.assertIn("42%", result["uncertain_questions"][0]["question_for_user"])

        # Crear borrador de cesta de compra (NUNCA compra sola)
        cart = dew.inventory.create_shopping_cart_draft(
            store="Mercadona",
            items=[
                {"name": "Pack 6 Leche sin lactosa", "qty": 1, "est_price_eur": 6.30},
                {"name": "Lavavajillas mano concentrado", "qty": 1, "est_price_eur": 1.85},
            ],
            budget_limit_eur=15.00,
        )
        self.assertEqual(cart["status"], "DRAFT_PENDING_REVIEW")
        self.assertTrue(cart["requires_user_confirmation"])
        self.assertAlmostEqual(cart["estimated_total_eur"], 8.15)

        confirmed = dew.inventory.confirm_shopping_cart(cart["cart_id"])
        self.assertEqual(confirmed["status"], "CONFIRMED_BY_USER")

    def test_04_chemical_safety_guardrail(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        unsafe_check = dew.inventory.validate_cleaning_advice_safety(
            "Mezcla lejía con un poco de vinagre de limpieza para quitar la cal."
        )
        self.assertFalse(unsafe_check["safe"])
        self.assertIn("ALERTA DE SEGURIDAD", unsafe_check["safe_replacement_message"])

        safe_check = dew.inventory.validate_cleaning_advice_safety(
            "Limpia la encimera con agua templada y jabón neutro usando una bayeta."
        )
        self.assertTrue(safe_check["safe"])

    def test_05_domotics_protected_entities_and_critical_locks(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=12.0)

        dew.domotics.register_entity(SmartDeviceEntity(
            entity_id="light.salon", friendly_name="Luz del Salón", domain="light", area="salon", state="on"
        ))
        dew.domotics.register_entity(SmartDeviceEntity(
            entity_id="switch.router_fibra", friendly_name="Enchufe Router Fibra", domain="switch", area="salon", state="on", protected=True
        ))
        dew.domotics.register_entity(SmartDeviceEntity(
            entity_id="climate.termostato_salon", friendly_name="Termostato Salón", domain="climate", area="salon", state="20.0", online=False
        ))
        dew.domotics.register_entity(SmartDeviceEntity(
            entity_id="lock.puerta_calle", friendly_name="Cerradura Puerta Calle", domain="lock", area="entrada", state="locked"
        ))

        # 1. Apagar todo el salón: apaga la luz, protege el router y avisa del termostato desconectado
        res_area = dew.domotics.execute_or_propose_command(area="salon", action="turn_off")
        self.assertEqual(len(res_area["executed"]), 1)
        self.assertIn("Enchufe Router Fibra", res_area["skipped_protected"])
        self.assertIn("Termostato Salón", res_area["offline_devices"])

        # 2. Abrir cerradura sin confirmación explícita queda retenido en pending_confirmation
        res_lock = dew.domotics.execute_or_propose_command(
            entity_id="lock.puerta_calle", action="unlock", user_confirmed_critical=False
        )
        self.assertEqual(len(res_lock["executed"]), 0)
        self.assertEqual(len(res_lock["pending_confirmation"]), 1)

        # 3. Con confirmación explícita sí se ejecuta y se audita
        res_lock_ok = dew.domotics.execute_or_propose_command(
            entity_id="lock.puerta_calle", action="unlock", user_confirmed_critical=True
        )
        self.assertEqual(len(res_lock_ok["executed"]), 1)

    def test_06_spanish_services_handoff_and_disclaimers(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        med_handoff = dew.spanish_services.prepare_medical_appointment_handoff(
            region_key="madrid",
            reason_notes_for_doctor="Revisar analítica anual",
        )
        self.assertEqual(med_handoff["integration_tier"], "TIER_2_PREPARE_AND_HANDOFF")
        self.assertEqual(med_handoff["service"]["android_package"], "es.madrid.salud.citasanitaria")
        self.assertIn("no es médico", med_handoff["medical_disclaimer"])
        self.assertTrue(med_handoff["requires_explicit_user_action"])

        aeat_handoff = dew.spanish_services.prepare_aeat_or_carpeta_ciudadana_handoff(
            procedure_type="renta_borrador",
            user_notes="Incluir factura de eficiencia energética y deducción autonómica",
        )
        self.assertEqual(aeat_handoff["official_app_package"], "es.aeat.agenciatributaria")
        self.assertIn("no es asesor fiscal", aeat_handoff["disclaimer"])

    def test_07_sequential_ram_and_think_switch_in_voice_turn(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)
        built = dew.prepare_voice_turn("Apunta que se ha acabado el papel de cocina")
        self.assertEqual(built.mode, "fast")
        self.assertTrue(built.full_prompt.endswith("<|im_start|>assistant\n<think>\n</think>\n"))

        simulated_llm_json = json.dumps({
            "spoken_reply": "Anotado que se ha terminado el papel de cocina. ¿Lo incluyo en tu próxima cesta?",
            "thinking_mode_used": False,
            "uncertainty_notes": [],
            "proposed_actions": [
                {
                    "tool": "update_inventory",
                    "requires_confirmation": False,
                    "payload": {"name": "Papel de cocina", "qty": 0},
                }
            ],
        }, ensure_ascii=False)
        final_turn = dew.validate_and_finalize_turn(simulated_llm_json)
        self.assertTrue(final_turn["is_valid"])
        # Verificar transiciones secuenciales de RAM en el móvil de 8 GB
        self.assertEqual(len(final_turn["memory_transitions"]), 3)
        self.assertIn("UNLOAD(STT_WHISPER_BASE_INT8) -> LOAD(LLM_DEW_9B_COMPACT_8GB)", final_turn["memory_transitions"][1])

    def test_08_spanish_receipt_ocr_parser_and_wifi_downloader(self) -> None:
        raw_ticket = (
            "MERCADONA S.A.\n"
            "2 L.ENT.S/LACT HAC 2,10\n"
            "1 PECH.PAVO LONCH 2,15\n"
            "1 LAVAVAJ.MANO B.VERDE 1,85\n"
            "TOTAL 6,10 EUR\n"
        )
        parsed = parse_spanish_receipt_ocr(raw_ticket)
        self.assertEqual(parsed["store"], "Mercadona")
        self.assertEqual(parsed["item_count"], 3)
        self.assertAlmostEqual(parsed["calculated_total_eur"], 6.10)
        categories = [i["category"] for i in parsed["items"]]
        self.assertIn("alimentacion", categories)
        self.assertIn("limpieza", categories)

        # Verificar que el descargador de modelos bloquea datos móviles por defecto y acepta Wi-Fi
        root = Path(__file__).resolve().parent.parent
        manifest_path = root / "model_pipeline" / "dist" / "dew_mobile_bundle_manifest.json"
        dl_mgr = DewModelDownloadManager(manifest_path, root / "model_pipeline" / "dist")

        cell_check = dl_mgr.check_download_eligibility(
            "DEW_9B_COMPACT_8GB", network_type="cellular", allow_cellular_override=False, simulated_free_disk_mb=15000
        )
        self.assertFalse(cell_check.can_start)
        self.assertIn("datos móviles", cell_check.reason)

        wifi_check = dl_mgr.check_download_eligibility(
            "DEW_9B_COMPACT_8GB", network_type="wifi", simulated_free_disk_mb=15000
        )
        self.assertTrue(wifi_check.can_start)

    def test_09_mobile_ui_api_actions_end_to_end(self) -> None:
        res_turn = handle_api_action({
            "action": "voice_or_text_turn",
            "utterance": "Planifícame el menú semanal de cenas con presupuesto de 30 euros",
        })
        self.assertTrue(res_turn["ok"])
        self.assertEqual(res_turn["turn_result"]["mode"], "deep_think")

        res_chem = handle_api_action({
            "action": "voice_or_text_turn",
            "utterance": "¿Puedo mezclar lejía con amoniaco?",
        })
        self.assertTrue(res_chem["ok"])
        self.assertIsNotNone(res_chem["turn_result"]["chemical_hazard"])

    def test_10_native_cpp_jni_contract_matches_kotlin_bridge(self) -> None:
        root = Path(__file__).resolve().parent.parent
        cpp_text = (root / "android_app" / "src" / "main" / "cpp" / "dew_jni_bridge.cpp").read_text(encoding="utf-8")
        kt_text = (
            root / "android_app" / "src" / "main" / "java" / "es" / "dew" / "assistant" / "core" / "DewNativeBridge.kt"
        ).read_text(encoding="utf-8")

        expected_methods = [
            "nativeInitModel",
            "nativeLoadPromptCache",
            "nativeGenerateStructuredJson",
            "nativeOnTrimMemoryPressure",
            "nativeUnloadModel",
            "nativeGetStatusJson",
        ]
        for method in expected_methods:
            self.assertIn(f"external fun {method}", kt_text)
            self.assertIn(f"Java_es_dew_assistant_core_DewNativeBridge_{method}", cpp_text)

    def test_11_offline_spanish_voice_pipeline_vad_stt_tts(self) -> None:
        voice = DewLocalVoiceEngine()

        # 1. Silencio puro -> VAD detecta que no hay voz y no ejecuta Whisper
        silence_pcm = [0.0005] * 8000
        res_silence = voice.transcribe_pcm_16k(silence_pcm)
        self.assertFalse(res_silence.vad_speech_detected)
        self.assertEqual(res_silence.normalized_text, "")

        # 2. Señal con voz + homófonos típicos en español doméstico -> VAD recorta y normaliza
        speech_pcm = [0.0] * 1600 + [0.25 * math.sin(i * 0.1) for i in range(8000)] + [0.0] * 1600
        res_speech = voice.transcribe_pcm_16k(
            speech_pcm,
            simulated_transcript_hint="Apunta leche sin la tosa de ha cendado en merca dona y clabe movil",
        )
        self.assertTrue(res_speech.vad_speech_detected)
        self.assertEqual(
            res_speech.normalized_text,
            "Apunta leche sin lactosa de Hacendado en Mercadona y Cl@ve Móvil",
        )

        # 3. Síntesis Piper TTS: recorta a máximo 2 frases, expande unidades (€, ºC, L) y genera WAV válido
        tts_res = voice.synthesize_spanish_speech(
            "La cesta cuesta 14,50 € por 1,5 L de leche y el salón está a 21 ºC. "
            "¿Confirmas la lista? Esta tercera frase se recorta por brevedad VUI."
        )
        self.assertIn("14,50 euros", tts_res.phonetic_text)
        self.assertIn("1,5 litros", tts_res.phonetic_text)
        self.assertIn("21 grados", tts_res.phonetic_text)
        self.assertNotIn("tercera frase", tts_res.phonetic_text)
        self.assertTrue(tts_res.wav_bytes.startswith(b"RIFF"))

    def test_12_household_p2p_lan_sync_crdt_and_security(self) -> None:
        # Dos móviles independientes en la misma casa (Móvil A y Móvil B)
        phone_a = DewAssistantOrchestrator(device_ram_gb=8.0)
        phone_b = DewAssistantOrchestrator(device_ram_gb=12.0)

        # Móvil A añade leche y también guarda un trámite médico privado (que NO debe sincronizarse)
        phone_a.inventory.upsert_inventory_item("Leche sin lactosa", "alimentacion", 6.0, "bricks")
        phone_a.spanish_services.prepare_medical_appointment_handoff("madrid", "Dolor de oído privado")

        # Móvil B tenía un dato antiguo de leche (1 brick) pero acaba de actualizar detergente
        phone_b.inventory.upsert_inventory_item("Pastillas lavavajillas", "limpieza", 30.0, "pastillas")

        sync_a = HouseholdLanSyncEngine(
            phone_a.storage, node_id="movil-principal", household_id="hogar-demo-01", pairing_code="849201"
        )
        sync_b = HouseholdLanSyncEngine(
            phone_b.storage, node_id="movil-secundario", household_id="hogar-demo-01", pairing_code="849201"
        )

        # 1. Móvil A envía paquete firmado a Móvil B
        packet_from_a = sync_a.build_signed_sync_packet()
        self.assertNotIn("spanish_procedures", packet_from_a["body"])

        merge_res_b = sync_b.verify_and_merge_sync_packet(packet_from_a)
        self.assertEqual(merge_res_b["status"], "SYNC_OK")
        self.assertEqual(phone_b.inventory.get_item("Leche sin lactosa")["qty"], 6.0)
        # Verificar que el trámite médico privado de A NO existe en B
        b_exported = phone_b.storage.export_all_user_data()
        self.assertEqual(len(b_exported["spanish_procedures"]), 0)

        # 2. Móvil B envía su estado de vuelta a Móvil A -> ambos convergen con leche (6) y pastillas (30)
        packet_from_b = sync_b.build_signed_sync_packet()
        sync_a.verify_and_merge_sync_packet(packet_from_b)
        self.assertEqual(phone_a.inventory.get_item("Pastillas lavavajillas")["qty"], 30.0)

        # 3. Un intruso en la red Wi-Fi con PIN erróneo o paquete alterado es bloqueado por HMAC-SHA256
        attacker = HouseholdLanSyncEngine(
            phone_b.storage, node_id="intruso", household_id="hogar-demo-01", pairing_code="000000"
        )
        bad_packet = attacker.build_signed_sync_packet()
        with self.assertRaises(PermissionError):
            sync_a.verify_and_merge_sync_packet(bad_packet)

    def test_13_flexible_meal_planner_custom_budget_diners_and_recipes(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        # El usuario tiene queso fresco que caduca mañana y lavavajillas casi agotado
        dew.inventory.upsert_inventory_item(
            "Queso fresco sin lactosa", "alimentacion", 1.0, "tarrina 250g", expiry_in_days=1, last_price_eur=1.40
        )
        dew.inventory.upsert_inventory_item(
            "Lavavajillas mano concentrado", "limpieza", 0.1, "botella", last_price_eur=1.85
        )

        # Además el usuario registra su propia receta casera favorita
        dew.meal_planner.register_custom_recipe(
            HouseholdRecipe(
                recipe_id="revuelto_setas_casa",
                title="Revuelto casero de setas y huevos",
                prep_minutes=12,
                tags=["sin_lactosa", "sin_gluten", "rapido"],
                ingredients=[
                    RecipeIngredient("Setas laminadas", 0.15, "bandeja", 1.95),
                    RecipeIngredient("Huevos camperos", 2.0, "unidades", 0.25),
                ],
            )
        )

        # Configuración 100% personalizada por el usuario: 3 comensales, presupuesto 42.50 €, 4 días
        user_cfg = HouseholdPlanningConfig(
            diners_count=3,
            weekly_budget_limit_eur=42.50,
            preferred_store="Consum",
            days_to_plan=["Lunes", "Martes", "Miércoles", "Jueves"],
            max_prep_minutes_by_day={"Martes": 12, "Jueves": 12},
            dietary_restrictions=["sin_lactosa"],
            excluded_ingredients=["cilantro"],
            include_low_stock_cleaning_items=True,
        )
        plan_res = dew.meal_planner.generate_plan_and_shopping_cart(user_cfg)

        self.assertEqual(plan_res["config_applied"]["diners_count"], 3)
        self.assertEqual(plan_res["config_applied"]["weekly_budget_limit_eur"], 42.50)
        self.assertEqual(len(plan_res["meal_plan"]), 4)
        self.assertTrue(plan_res["budget_summary"]["within_budget"])
        # El lunes debe haber priorizado la receta que usa el queso fresco que caduca mañana
        self.assertIn("Queso fresco sin lactosa", plan_res["meal_plan"][0]["uses_expiring_ingredients"])

    def test_14_barcode_scanner_and_flexible_user_allergen_guard(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        # El usuario configura sus propios alérgenos e ingredientes a evitar en casa
        dew.barcode_service.configure_household_allergens(
            ["lactosa", "cacahuete", "aceite de palma"], consent_granted=True
        )

        # 1. Escanear leche SIN lactosa (8480000107046) -> Segura, se añade al inventario
        scan_safe = dew.barcode_service.scan_barcode("8480000107046", qty_to_add=6.0, user_price_eur=1.05)
        self.assertTrue(scan_safe["found"])
        self.assertTrue(scan_safe["allergen_check"]["safe_for_household"])
        self.assertTrue(scan_safe["added_to_inventory"])

        # 2. Escanear crema de cacahuete (8480000231406) -> Detecta conflicto con 'cacahuete' y bloquea auto-añadido
        scan_conflict = dew.barcode_service.scan_barcode("8480000231406", qty_to_add=1.0)
        self.assertTrue(scan_conflict["found"])
        self.assertFalse(scan_conflict["allergen_check"]["safe_for_household"])
        self.assertIn("cacahuete", scan_conflict["allergen_check"]["conflicts"])
        self.assertFalse(scan_conflict["added_to_inventory"])

    def test_15_local_history_rag_fts5_and_multi_store_price_comparison(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)

        # Registrar compras del mismo producto en 3 comercios distintos elegidos por el usuario
        dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Carrefour", 8.45, qty=1, unit="L")
        dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Mercadona", 7.65, qty=1, unit="L")
        dew.history_search.record_purchase_item("Aceite de oliva virgen extra 1L", "Cooperativa Local", 6.90, qty=2, unit="L")
        dew.history_search.record_purchase_item("Detergente líquido Marsella", "Mercadona", 4.90, qty=1, category="limpieza")

        # 1. Comparar precios entre tiendas
        comp = dew.history_search.compare_product_prices_across_stores("Aceite de oliva")
        self.assertTrue(comp["found"])
        self.assertEqual(comp["best_offer"]["store"], "Cooperativa Local")
        self.assertAlmostEqual(comp["best_offer"]["unit_price_eur"], 6.90)
        self.assertAlmostEqual(comp["potential_savings_per_unit_eur"], 1.55)

        # 2. Resumen de gasto frente a cualquier presupuesto personalizado del usuario (ej. 50 €)
        spend = dew.history_search.get_flexible_spending_summary(custom_budget_limit_eur=50.00)
        self.assertTrue(spend["within_budget"])
        self.assertAlmostEqual(spend["total_spent_eur"], round(8.45 + 7.65 + 13.80 + 4.90, 2))

        # 3. Búsqueda RAG local FTS5 sobre notas del hogar
        dew.history_search.add_household_note(
            "Filtro de la lavadora Bosch",
            "Limpiar el filtro inferior derecho cada 3 meses abriendo la trampilla con una moneda.",
        )
        snippets = dew.history_search.search_relevant_context_snippets("cómo limpiar filtro lavadora")
        self.assertGreaterEqual(len(snippets), 1)
        self.assertIn("lavadora", snippets[0]["body"].lower())

    def test_16_colab_notebook_and_cloud_publisher_integrity(self) -> None:
        root = Path(__file__).resolve().parent.parent
        nb_path = root / "model_pipeline" / "notebooks" / "Dew_Qwen38_9B_Quantization_Colab.ipynb"
        self.assertTrue(nb_path.exists())
        nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
        self.assertEqual(nb_data["nbformat"], 4)
        self.assertGreaterEqual(len(nb_data["cells"]), 5)

        manifest_path = root / "model_pipeline" / "dist" / "dew_mobile_bundle_manifest.json"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_manifest = Path(tmpdir) / "dew_mobile_bundle_manifest.json"
            shutil.copy2(manifest_path, tmp_manifest)
            updated = update_manifest_with_built_artifacts(
                manifest_path=tmp_manifest,
                dist_dir=root / "model_pipeline" / "dist",
                download_base_url="https://huggingface.co/CeuTryharder/Dew-Qwen3.8-9B-Mobile-ES-GGUF/resolve/main",
            )
            self.assertEqual(len(updated["tiers"]), 2)
            self.assertIn(
                "https://huggingface.co/CeuTryharder/Dew-Qwen3.8-9B-Mobile-ES-GGUF/resolve/main/dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf",
                updated["tiers"][0]["download_url"],
            )

        card = generate_huggingface_model_card("CeuTryharder/Dew-Qwen3.8-9B-Mobile-ES-GGUF")
        self.assertIn("apache-2.0", card)
        self.assertIn("empero-ai/Qwen3.8-9B-Distill", card)

    def test_17_regression_lock_states_and_fractional_receipt_unit_price(self) -> None:
        dew = DewAssistantOrchestrator(device_ram_gb=8.0)
        dew.domotics.register_entity(SmartDeviceEntity(
            entity_id="lock.entrada", friendly_name="Cerradura Entrada", domain="lock", area="entrada", state="locked"
        ))
        res_unlock = dew.domotics.execute_or_propose_command(
            entity_id="lock.entrada", action="unlock", user_confirmed_critical=True
        )
        self.assertEqual(len(res_unlock["executed"]), 1)
        self.assertEqual(dew.domotics.entities["lock.entrada"].state, "unlocked")

        res_lock = dew.domotics.execute_or_propose_command(
            entity_id="lock.entrada", action="lock", user_confirmed_critical=True
        )
        self.assertEqual(len(res_lock["executed"]), 1)
        self.assertEqual(dew.domotics.entities["lock.entrada"].state, "locked")

        parsed = parse_spanish_receipt_ocr("MERCADONA S.A.\n0,5 TOMATE PERA 1,20\nTOTAL 1,20 EUR\n")
        self.assertEqual(parsed["item_count"], 1)
        self.assertAlmostEqual(parsed["items"][0]["unit_price_eur"], 2.40)


if __name__ == "__main__":
    unittest.main()
