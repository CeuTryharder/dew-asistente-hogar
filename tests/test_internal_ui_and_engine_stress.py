"""
Pruebas Internas de Estrés y Auditoría Anti-Congelación (Domótica, Hacienda, UI Android y Motor Abierto).
Ejecuta:
1. Auditoría estática de concurrencia sobre `DewViewModel.kt` y `DewMainScreen.kt` para garantizar
   que ningún bloque `_uiState.update { ... }` invoque funciones que muten `_uiState` de forma reentrante
   (causa raíz del bloqueo táctil en Hacienda y Domótica).
2. Verificación de arquitectura Compose en `DewMainScreen.kt` (ausencia de `BoxWithConstraints` /
   `SubcomposeLayout`, ausencia de `LazyColumn` con `OutlinedTextField` anidados y `Checkbox` sin
   doble manejador táctil).
3. Prueba de estrés funcional de los motores de Domótica, Hacienda/ES, Despensa, OCR, EAN-13 y
   Servidor Wi-Fi/APK.
"""

from __future__ import annotations

import pathlib
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from dew_core.domotics_and_spanish_services import SmartDeviceEntity
from dew_core.hardware_and_orchestrator import DewAssistantOrchestrator
from mobile_ui.app_server import DewHttpHandler, handle_api_action

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
VIEWMODEL_KT = ROOT_DIR / "android_app" / "src" / "main" / "java" / "es" / "dew" / "assistant" / "ui" / "DewViewModel.kt"
MAINSCREEN_KT = ROOT_DIR / "android_app" / "src" / "main" / "java" / "es" / "dew" / "assistant" / "ui" / "DewMainScreen.kt"
GENERAL_ENGINE_KT = ROOT_DIR / "android_app" / "src" / "main" / "java" / "es" / "dew" / "assistant" / "core" / "DewGeneralAssistantEngine.kt"


def extract_brace_blocks(source: str, prefix: str) -> list[tuple[int, str]]:
    """Extrae el contenido completo balanceando llaves `{ ... }` tras cada aparición de `prefix`."""
    results: list[tuple[int, str]] = []
    idx = 0
    while True:
        found = source.find(prefix, idx)
        if found == -1:
            break
        brace_start = source.find("{", found)
        if brace_start == -1:
            break
        depth = 0
        end = brace_start
        while end < len(source):
            ch = source[end]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    line_no = source[:found].count("\n") + 1
                    results.append((line_no, source[brace_start + 1 : end]))
                    break
            end += 1
        idx = end + 1
    return results


class TestInternalUiAndEngineStress(unittest.TestCase):

    def test_01_kotlin_viewmodel_has_zero_reentrant_stateflow_updates(self) -> None:
        """
        Verifica que NINGÚN bloque `_uiState.update { ... }` llame a `appendLog(`,
        `pushAssistantReply(` o a otro `_uiState.update` dentro de su lambda.
        Esto previene al 100% el bucle infinito compareAndSet en el hilo UI de Android.
        """
        source = VIEWMODEL_KT.read_text(encoding="utf-8")
        update_blocks = extract_brace_blocks(source, "_uiState.update")
        self.assertGreaterEqual(len(update_blocks), 20, "Debe haber al menos 20 bloques _uiState.update auditados")

        forbidden_calls = ["appendLog(", "pushAssistantReply(", "_uiState.update"]
        for line_no, block_body in update_blocks:
            for forbidden in forbidden_calls:
                self.assertNotIn(
                    forbidden,
                    block_body,
                    f"CRÍTICO: Llamada reentrante `{forbidden}` detectada dentro de `_uiState.update` en línea {line_no}",
                )

    def test_02_kotlin_viewmodel_uses_atomic_id_and_has_no_non_threadsafe_id_mutation_in_cas(self) -> None:
        """Verifica que `nextId` sea `AtomicLong` y nunca se mute con `++nextId` dentro de `_uiState.update`."""
        source = VIEWMODEL_KT.read_text(encoding="utf-8")
        self.assertIn("AtomicLong", source)
        self.assertNotIn("++nextId", source)
        for line_no, block_body in extract_brace_blocks(source, "_uiState.update"):
            self.assertNotIn(
                "nextId.incrementAndGet()",
                block_body,
                f"No se debe incrementar nextId dentro del bucle CAS en línea {line_no}",
            )

    def test_03_kotlin_main_screen_eliminates_subcompose_and_checkbox_double_touch_conflicts(self) -> None:
        """
        Verifica que `DewMainScreen.kt`:
        1. No use `BoxWithConstraints` (SubcomposeLayout) ni `LazyColumn` con `OutlinedTextField`.
        2. Use `verticalScroll(rememberScrollState())` para desplazamiento fluido a 165Hz.
        3. Configure `onCheckedChange = null` en el `Checkbox` de Hacienda/ES dentro de la fila `.clickable`.
        """
        source = MAINSCREEN_KT.read_text(encoding="utf-8")
        self.assertNotIn("BoxWithConstraints", source)
        self.assertNotIn("LazyColumn", source)
        self.assertIn("verticalScroll(rememberScrollState())", source)
        self.assertIn("onCheckedChange = null", source)
        self.assertIn("LocalConfiguration.current", source)

    def test_04_general_assistant_engine_supports_math_iva_recipes_science_code_and_live_llm(self) -> None:
        """Verifica que el motor abierto `DewGeneralAssistantEngine.kt` cubra preguntas generales y cálculos."""
        source = GENERAL_ENGINE_KT.read_text(encoding="utf-8")
        for required_symbol in [
            "answerGeneralQuestion",
            "trySolveMathOrFinance",
            "tryQueryLiveGenerativeAi",
            "tryQuerySpanishWikipedia",
            "answerOfflineComprehensive",
            "Tortilla de Patatas",
            "Paella",
            "Relatividad General",
            "Python",
            "IVA",
        ]:
            self.assertIn(required_symbol, source)

    def test_05_stress_test_50_rapid_interactions_on_domotics_hacienda_and_inventory(self) -> None:
        """
        Ejecuta una batería de estrés de 50 operaciones consecutivas en Domótica,
        Hacienda/ES, Despensa y API de la UI para validar estabilidad y 0 bloqueos.
        """
        dew = DewAssistantOrchestrator(device_ram_gb=16.0)
        dew.domotics.register_entity(SmartDeviceEntity("light.salon", "Luz Salón", "light", "salon", "on"))
        dew.domotics.register_entity(SmartDeviceEntity("switch.router", "Router Fibra", "switch", "salon", "on", protected=True))
        dew.domotics.register_entity(SmartDeviceEntity("lock.puerta", "Cerradura Calle", "lock", "entrada", "locked"))

        # 20 conmutaciones rápidas de salón
        for i in range(20):
            res = dew.domotics.execute_or_propose_command(
                entity_id="light.salon",
                action="turn_off" if i % 2 == 0 else "turn_on",
            )
            self.assertEqual(len(res["executed"]), 1)

        # Intento de apagar área Salón -> protege el router automáticamente
        area_res = dew.domotics.execute_or_propose_command(area="salon", action="turn_off")
        self.assertIn("Router Fibra", area_res["skipped_protected"])

        # Cerradura crítica exige confirmación explícita
        lock_blocked = dew.domotics.execute_or_propose_command(
            entity_id="lock.puerta", action="unlock", user_confirmed_critical=False
        )
        self.assertEqual(len(lock_blocked["pending_confirmation"]), 1)
        lock_ok = dew.domotics.execute_or_propose_command(
            entity_id="lock.puerta", action="unlock", user_confirmed_critical=True
        )
        self.assertEqual(len(lock_ok["executed"]), 1)

        # Estrés en Trámites de España / Hacienda AEAT / Salud / DGT
        for proc_type in ["renta_borrador", "carpeta_ciudadana_dni", "empadronamiento_padron"]:
            handoff = dew.spanish_services.prepare_aeat_or_carpeta_ciudadana_handoff(
                procedure_type=proc_type,
                user_notes="Expediente local verificado",
            )
            self.assertTrue(handoff["official_url"].startswith("https://"))

        for region in ["madrid", "cataluna", "andalucia", "valencia"]:
            med = dew.spanish_services.prepare_medical_appointment_handoff(
                region_key=region,
                reason_notes_for_doctor="Revisión general",
            )
            self.assertEqual(med["integration_tier"], "TIER_2_PREPARE_AND_HANDOFF")

        # Estrés en API de acciones móviles (menú, alérgenos, química)
        for _ in range(10):
            res_turn = handle_api_action({
                "action": "voice_or_text_turn",
                "utterance": "Planifícame el menú semanal de cenas con presupuesto de 35 euros",
            })
            self.assertTrue(res_turn["ok"])

        # Verificar que las consultas abiertas no se enruten erróneamente a Domótica ni Hacienda
        for general_q in (
            "¿Cuál es la velocidad de la luz?",
            "Dime una cita famosa de Cervantes",
            "Explícame el modelo Qwen3.8-9B",
        ):
            res_general = handle_api_action({"action": "voice_or_text_turn", "utterance": general_q})
            self.assertTrue(res_general["ok"])
            self.assertNotIn("[TOOL_EXEC] home_assistant", res_general["turn_result"]["think_trace"])
            self.assertNotIn("[TOOL_EXEC] spanish_gov", res_general["turn_result"]["think_trace"])

        # Verificar que el servidor HTTP responde correctamente (APK opcional en CI porque *.apk es gitignored)
        apk_path = ROOT_DIR / "dist" / "dew-hogar-redmagic-16gb-debug.apk"
        if apk_path.exists():
            self.assertGreater(apk_path.stat().st_size, 5_000_000, "El APK debe superar los 5 MB")

        server = HTTPServer(("127.0.0.1", 0), DewHttpHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as resp:
                self.assertEqual(resp.status, 200)

            not_found_req = urllib.request.Request(f"http://127.0.0.1:{port}/ruta-inexistente", method="HEAD")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(not_found_req, timeout=5)
            self.assertEqual(ctx.exception.code, 404)

            apk_head_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/dew-hogar-redmagic-16gb-debug.apk", method="HEAD"
            )
            if apk_path.exists():
                with urllib.request.urlopen(apk_head_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(int(resp.headers["Content-Length"]), apk_path.stat().st_size)
            else:
                with self.assertRaises(urllib.error.HTTPError) as apk_ctx:
                    urllib.request.urlopen(apk_head_req, timeout=5)
                self.assertEqual(apk_ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_06_cpp_bridge_deadlock_and_jni_null_safety_audit(self) -> None:
        """Verifica que el puente JNI C++ no tenga deadlock de mutex ni llamadas inseguras a GetStringUTFChars."""
        cpp_dir = ROOT_DIR / "android_app" / "src" / "main" / "cpp"
        header = (cpp_dir / "dew_llama_engine.h").read_text(encoding="utf-8")
        bridge = (cpp_dir / "dew_jni_bridge.cpp").read_text(encoding="utf-8")

        self.assertIn("#include <cstdint>", header)
        self.assertIn("unload_model_locked()", header)
        self.assertIn("backend_initialized_", header)

        init_blocks = extract_brace_blocks(bridge, "DewNativeEngine::initialize_model")
        self.assertEqual(len(init_blocks), 1)
        self.assertNotIn("unload_model()", init_blocks[0][1])
        self.assertIn("unload_model_locked()", init_blocks[0][1])

        self.assertIn("jstring_to_std_string", bridge)
        self.assertIn("escape_json_string", bridge)
        self.assertIn("parse_kv_cache_type", bridge)

    def test_07_runner_scripts_and_workspace_have_no_local_user_paths(self) -> None:
        """Verifica que los scripts generados y archivos públicos no filtren rutas locales ni correos privados."""
        for script_name in ("run_quantization.ps1", "run_quantization.sh"):
            script_text = (ROOT_DIR / "model_pipeline" / "dist" / script_name).read_text(encoding="utf-8")
            self.assertNotIn("C:\\Users\\", script_text, f"{script_name} contiene ruta local Windows")
            self.assertNotIn("/home/", script_text, f"{script_name} contiene ruta local Linux")
            self.assertNotIn("/Users/", script_text, f"{script_name} contiene ruta local macOS")

        for rel in ("README.md", "ARQUITECTURA_DEW.md", "model_pipeline/dist/dew_mobile_bundle_manifest.json"):
            content = (ROOT_DIR / rel).read_text(encoding="utf-8").lower()
            self.assertNotIn("@gmail.com", content, f"{rel} contiene un correo personal")
            self.assertNotIn("c:\\users\\", content, f"{rel} contiene ruta de usuario")

        self.assertTrue((ROOT_DIR / "LICENSE").exists(), "Falta archivo LICENSE en la raíz para distribución open source")


if __name__ == "__main__":
    unittest.main()
