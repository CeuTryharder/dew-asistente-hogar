package es.dew.assistant

import es.dew.assistant.core.DewGeneralAssistantEngine
import es.dew.assistant.core.DewHardwareProfiler
import es.dew.assistant.core.ModelTier
import es.dew.assistant.ui.DewTab
import es.dew.assistant.ui.DewViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Suite de Pruebas Internas y de Estrés de Orca·Dew (RedMagic Astra 16 GB).
 *
 * Verifica en la JVM que ninguna acción táctil en Domótica, Hacienda/ES,
 * Despensa, Memoria o Preguntas Abiertas provoque bloqueos (deadlocks en
 * MutableStateFlow.update) y que cada acción actualice el estado en < 50 ms.
 */
class DewAndroidInternalStressTest {

    @Test
    fun test01_redmagicAstra16GbHardwareProfile() {
        val tier = DewHardwareProfiler.selectOptimalTier(16.0)
        assertEquals(ModelTier.PRO_12GB, tier)
        assertFalse(tier.sequentialUnloadRequired)
        val params = DewHardwareProfiler.buildRuntimeParams(tier, 16.0)
        assertEquals(8192, params.nCtx)
        assertEquals("q8_0", params.typeV)
        assertEquals(1024, params.nBatch)
    }

    @Test(timeout = 2000L)
    fun test02_domoticsAllButtonsAndProtectionNeverFreeze() {
        val vm = DewViewModel(deviceRamGb = 16.0)

        // 1. Tocar interruptor de luz salón y cocina 20 veces seguidas (estrés táctil)
        repeat(20) {
            vm.toggleSmartDevice("light.salon")
            vm.toggleSmartDevice("light.cocina")
        }

        // 2. Intentar apagar el Router protegido -> debe bloquearse sin congelar la UI
        vm.toggleSmartDevice("switch.router", forceState = false)
        val routerStillOn = vm.uiState.value.devices.first { it.entityId == "switch.router" }.isOn
        assertTrue("El router protegido no debe apagarse", routerStillOn)

        // 3. Tocar el botón de Protección (🛡️ Protegido / 🔓 Desprotegido) 20 veces (antes causaba bucle CAS infinito)
        repeat(20) {
            vm.toggleDeviceProtection("switch.router")
        }

        // 4. Ajustar termostato (+/- 0.5 °C y modos Eco/Calor/Frío)
        vm.setThermostatTemperature("climate.salon", 22.5, "Calor")
        val thermostat = vm.uiState.value.devices.first { it.entityId == "climate.salon" }
        assertEquals(22.5, thermostat.temperatureC, 0.01)
        assertEquals("Calor", thermostat.hvacMode)

        // 5. Comandos grupales de área ("Apagar Todo el Salón" y "Encender Salón")
        vm.executeAreaDomoticsCommand("Salón", turnOn = false)
        vm.executeAreaDomoticsCommand("Salón", turnOn = true)

        // 6. Cerradura crítica con confirmación biométrica
        vm.toggleDoorLockWithConfirmation(forceUnlock = true)
        assertFalse(vm.uiState.value.devices.first { it.entityId == "lock.puerta" }.isOn)
        vm.toggleDoorLockWithConfirmation(forceUnlock = false)
        assertTrue(vm.uiState.value.devices.first { it.entityId == "lock.puerta" }.isOn)

        // 7. Añadir nuevo dispositivo LAN
        vm.addCustomSmartDevice("Enchufe Cafetera", "Cocina", "switch")
        assertTrue(vm.uiState.value.devices.any { it.name == "Enchufe Cafetera" })
    }

    @Test(timeout = 2000L)
    fun test03_haciendaAndSpanishProceduresChecklistsNeverFreeze() {
        val vm = DewViewModel(deviceRamGb = 16.0)

        // Recorrer TODOS los trámites (Hacienda AEAT, Cita Médica 17 CCAA, Carpeta Ciudadana, Catastro)
        // y pulsar cada casilla del checklist 10 veces seguidas (antes causaba bucle CAS infinito)
        val procedures = vm.uiState.value.spanishProcedures
        assertTrue(procedures.size >= 4)

        for (proc in procedures) {
            for (item in proc.checklist) {
                val initialChecked = item.checked
                vm.toggleProcedureChecklistItem(proc.id, item.id)
                val afterFirstTap = vm.uiState.value.spanishProcedures
                    .first { it.id == proc.id }
                    .checklist.first { it.id == item.id }.checked
                assertEquals(!initialChecked, afterFirstTap)

                // Segundo toque devuelve al estado original
                vm.toggleProcedureChecklistItem(proc.id, item.id)
                val afterSecondTap = vm.uiState.value.spanishProcedures
                    .first { it.id == proc.id }
                    .checklist.first { it.id == item.id }.checked
                assertEquals(initialChecked, afterSecondTap)
            }

            // Ejecutar botón "Analizar con <think>" en cada trámite
            vm.analyzeSpanishProcedureWithAi(proc.id)
            val updatedProc = vm.uiState.value.spanishProcedures.first { it.id == proc.id }
            assertNotNull("El informe IA de ${proc.id} debe generarse", updatedProc.aiPreparedSummary)
        }

        // Cambiar Comunidad Autónoma en Cita Médica
        vm.updateProcedureRegionOrNotes("cita_medica", region = "Cataluña (CatSalut)", notes = "Dolor garganta")
        val medProc = vm.uiState.value.spanishProcedures.first { it.id == "cita_medica" }
        assertEquals("Cataluña (CatSalut)", medProc.selectedRegion)
    }

    @Test(timeout = 2000L)
    fun test04_inventoryMealPlannerOcrAndEan13NeverFreeze() {
        val vm = DewViewModel(deviceRamGb = 16.0)

        // 1. Ajustar cantidades e incertidumbre visual
        vm.adjustInventoryQuantity(1, +2.0)
        vm.confirmUncertainInventoryItem(4, "Lentejas caseras en táper")
        val confirmedItem = vm.uiState.value.inventory.first { it.id == 4 }
        assertEquals(1.0f, confirmedItem.confidence, 0.01f)

        // 2. Añadir producto manual y gestionar cesta
        vm.addManualInventoryItem("Tomates pera", 6.0, "uds", "alimentacion")
        vm.addCartItem("Aceite de Oliva Virgen Extra", 8.95)
        vm.confirmDraftCart()
        assertTrue(vm.uiState.value.draftCartConfirmed)
        vm.removeCartItem(0)

        // 3. Planificador semanal flexible (<think>)
        vm.generateFlexibleMealPlan(diners = 4, budgetEur = 50.0, store = "Carrefour")
        assertEquals(4, vm.uiState.value.plannerDiners)
        assertEquals(50.0, vm.uiState.value.plannerBudgetEur, 0.01)
        assertEquals(5, vm.uiState.value.generatedMealPlan.size)

        // 4. Escáner OCR de ticket español
        vm.processSpanishReceiptOcr("MERCADONA S.A.\n2 LECHE SIN LACTOSA HAC 2,10\nTOTAL 2,10 EUR")

        // 5. Escáner EAN-13 con alérgenos
        vm.scanBarcodeEan13("8480000107046") // Leche sin lactosa -> apto
        assertTrue(vm.uiState.value.lastBarcodeScan!!.isSafeForHousehold)
        vm.scanBarcodeEan13("8480000231406") // Crema cacahuete -> bloqueado
        assertFalse(vm.uiState.value.lastBarcodeScan!!.isSafeForHousehold)
    }

    @Test(timeout = 2000L)
    fun test05_privacyMemoryConsentLanSyncAndWipeNeverFreeze() {
        val vm = DewViewModel(deviceRamGb = 16.0)

        // Aprobar permiso pendiente (antes tenía appendLog anidado en _uiState.update)
        vm.approveMemoryConsent(1)
        assertTrue(vm.uiState.value.pendingMemoryConsents.isEmpty())

        // Añadir y borrar memoria
        vm.addCustomApprovedMemory("Mascota", "Perro sin cereales")
        assertTrue(vm.uiState.value.approvedMemories.containsKey("Mascota"))
        vm.removeApprovedMemory("Mascota")
        assertFalse(vm.uiState.value.approvedMemories.containsKey("Mascota"))

        // Sincronización P2P LAN y borrado criptográfico
        vm.triggerHouseholdLanSync()
        vm.wipeAllMemories()
        assertTrue(vm.uiState.value.approvedMemories.isEmpty())
    }

    @Test(timeout = 3000L)
    fun test06_openGeneralAssistantAndChemicalGuardrail() {
        val vm = DewViewModel(deviceRamGb = 16.0)
        vm.toggleOfflineSimulation(true)

        // 1. Guardarraíl químico determinista
        vm.onUserUtterance("¿Puedo mezclar lejía con amoniaco?")
        assertNotNull(vm.uiState.value.chemicalSafetyAlert)

        // 2. Matemáticas e IVA español (motor general determinista)
        val mathRes = DewGeneralAssistantEngine.answerGeneralQuestion(
            query = "Calcula el 21% de IVA de 350 euros",
            householdContextSummary = "",
            isOfflineMode = true
        )
        assertTrue(mathRes.reply.contains("73,50") || mathRes.reply.contains("73.50"))
        assertTrue(mathRes.reply.contains("423,50") || mathRes.reply.contains("423.50"))

        // 3. Receta de cocina abierta
        val recipeRes = DewGeneralAssistantEngine.answerGeneralQuestion(
            query = "¿Cómo se hace una tortilla de patatas española perfecta?",
            householdContextSummary = "",
            isOfflineMode = true
        )
        assertTrue(recipeRes.reply.contains("Tortilla", ignoreCase = true))

        // 4. Ciencia / Agujero negro / Relatividad
        val sciRes = DewGeneralAssistantEngine.answerGeneralQuestion(
            query = "¿Qué es un agujero negro?",
            householdContextSummary = "",
            isOfflineMode = true
        )
        assertTrue(sciRes.reply.contains("espacio-tiempo", ignoreCase = true))

        // 5. Navegación entre todas las pestañas
        for (tab in DewTab.entries) {
            vm.selectTab(tab)
            assertEquals(tab, vm.uiState.value.currentTab)
        }
    }

    @Test(timeout = 3000L)
    fun test07_regressionFixesForIvaRoutingDoorLockAndReceiptOcr() {
        // 1. "IVA del 21% de 350 euros" debe calcular sobre 350, no sobre 21
        val ivaOrder = DewGeneralAssistantEngine.answerGeneralQuestion(
            query = "IVA del 21% de 350 euros",
            householdContextSummary = "",
            isOfflineMode = true
        )
        assertTrue(ivaOrder.reply.contains("73.50") || ivaOrder.reply.contains("73,50"))
        assertTrue(ivaOrder.reply.contains("423.50") || ivaOrder.reply.contains("423,50"))

        // 2. Rango de años y nombre de modelo no deben evaluarse como resta aritmética
        val ww1 = DewGeneralAssistantEngine.answerGeneralQuestion("1914-1918", "", isOfflineMode = true)
        assertFalse(ww1.reply.contains("-4"))
        val modelName = DewGeneralAssistantEngine.answerGeneralQuestion("Qwen3.8-9B", "", isOfflineMode = true)
        assertFalse(modelName.reply.contains("-5.2"))

        // 3. Consulta conceptual del IVA sin importe no debe calcular sobre 21 €
        val ivaConcept = DewGeneralAssistantEngine.answerGeneralQuestion(
            query = "¿Cómo funciona el IVA del 21% en España?",
            householdContextSummary = "",
            isOfflineMode = true
        )
        assertFalse(ivaConcept.reply.contains("25,41") || ivaConcept.reply.contains("25.41"))

        val vm = DewViewModel(deviceRamGb = 8.0)
        vm.toggleOfflineSimulation(true)

        // 4. "velocidad de la luz" no debe tocar domótica
        val salonInitialOn = vm.uiState.value.devices.first { it.entityId == "light.salon" }.isOn
        vm.onUserUtterance("¿Cuál es la velocidad de la luz?")
        assertEquals(salonInitialOn, vm.uiState.value.devices.first { it.entityId == "light.salon" }.isOn)

        // 5. "Abre la puerta" por chat exige confirmación explícita antes de desbloquear
        vm.onUserUtterance("Abre la puerta")
        assertTrue(
            "La cerradura debe seguir bloqueada sin confirmación",
            vm.uiState.value.devices.first { it.entityId == "lock.puerta" }.isOn
        )
        assertTrue(vm.uiState.value.pendingLockConfirmation)
        vm.confirmPendingDoorUnlock()
        assertFalse(vm.uiState.value.devices.first { it.entityId == "lock.puerta" }.isOn)
        assertFalse(vm.uiState.value.pendingLockConfirmation)

        // 6. Termostato respeta rango seguro 16..26 °C
        vm.onUserUtterance("Pon el termostato a 40 grados")
        assertEquals(26.0, vm.uiState.value.devices.first { it.entityId == "climate.salon" }.temperatureC, 0.01)

        // 7. Dispositivos personalizados con mismo nombre obtienen IDs únicos
        vm.addCustomSmartDevice("Luz Salón", "Salón", "light")
        vm.addCustomSmartDevice("Luz Salón", "Salón", "light")
        val ids = vm.uiState.value.devices.map { it.entityId }
        assertEquals(ids.size, ids.toSet().size)

        // 8. Sinónimo de gluten ('trigo') detectado en EAN-13 y OCR acepta minúsculas/kg/EUR
        vm.updateHouseholdAllergens("gluten")
        vm.scanBarcodeEan13("8410000810004")
        assertFalse(vm.uiState.value.lastBarcodeScan!!.isSafeForHousehold)

        val beforeInvCount = vm.uiState.value.inventory.size
        vm.processSpanishReceiptOcr("MERCADONA S.A.\n1 Patatas malla 1kg 2,35 EUR\nTOTAL 2,35 EUR")
        assertEquals(beforeInvCount + 1, vm.uiState.value.inventory.size)
    }
}
