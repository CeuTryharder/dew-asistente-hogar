package es.dew.assistant.ui

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val BgObsidian = Color(0xFF090D16)
private val CardSlate = Color(0xFF111827)
private val TerminalBg = Color(0xFF05080F)
private val BorderSlate = Color(0xFF1E293B)
private val EmeraldAccent = Color(0xFF10B981)
private val CyanAccent = Color(0xFF38BDF8)
private val AmberThink = Color(0xFFF59E0B)
private val DangerRed = Color(0xFFEF4444)
private val TextPrimary = Color(0xFFF8FAFC)
private val TextMuted = Color(0xFF94A3B8)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DewMainScreen(viewModel: DewViewModel) {
    val state by viewModel.uiState.collectAsState()
    var inputText by remember { mutableStateOf("") }
    var showLockDialog by remember { mutableStateOf(false) }

    if (showLockDialog || state.pendingLockConfirmation) {
        AlertDialog(
            onDismissRequest = {
                showLockDialog = false
                if (state.pendingLockConfirmation) viewModel.dismissPendingDoorUnlock()
            },
            containerColor = CardSlate,
            titleContentColor = TextPrimary,
            textContentColor = TextMuted,
            title = { Text("🔐 Confirmación de Seguridad Crítica", fontWeight = FontWeight.Bold) },
            text = {
                Text("¿Autorizas con tu credencial biométrica cambiar el estado de la Cerradura Puerta Calle (`lock.puerta`) en la red LAN local?")
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (state.pendingLockConfirmation) {
                            viewModel.confirmPendingDoorUnlock()
                        } else {
                            viewModel.toggleDoorLockWithConfirmation()
                        }
                        showLockDialog = false
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = DangerRed)
                ) {
                    Text("Autorizar y Actuar", color = Color.White, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                OutlinedButton(
                    onClick = {
                        showLockDialog = false
                        if (state.pendingLockConfirmation) viewModel.dismissPendingDoorUnlock()
                    }
                ) {
                    Text("Cancelar", color = TextPrimary)
                }
            }
        )
    }

    Scaffold(
        containerColor = BgObsidian,
        topBar = {
            OrcaCommandHeader(
                state = state,
                onToggleTerminal = { viewModel.toggleTerminalDrawer() },
                onToggleOffline = { viewModel.toggleOfflineSimulation(!state.isOfflineMode) }
            )
        },
        bottomBar = {
            OrcaBottomNavigationBar(
                currentTab = state.currentTab,
                onSelectTab = { viewModel.selectTab(it) }
            )
        }
    ) { innerPadding ->
        val config = LocalConfiguration.current
        val isWideTablet = config.screenWidthDp >= 840 && config.screenWidthDp > config.screenHeightDp

        Box(
            modifier = Modifier
                .padding(innerPadding)
                .fillMaxSize()
                .background(BgObsidian)
                .padding(horizontal = 12.dp, vertical = 8.dp)
        ) {
            if (isWideTablet) {
                // Diseño de 2 columnas estilo Orca IDE para Tablet Horizontal (RedMagic Astra)
                Row(
                    modifier = Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Column(
                        modifier = Modifier
                            .weight(0.45f)
                            .fillMaxHeight(),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        OrcaPromptAndQuickBar(
                            state = state,
                            inputText = inputText,
                            onInputChange = { inputText = it },
                            onSend = {
                                if (inputText.isNotBlank()) {
                                    viewModel.onUserUtterance(inputText)
                                    inputText = ""
                                }
                            },
                            onQuickCommand = { cmd -> viewModel.onUserUtterance(cmd) }
                        )
                        if (state.showTerminalDrawer) {
                            OrcaLiveTerminalCard(
                                state = state,
                                onFilterChange = { viewModel.setTerminalFilter(it) },
                                onClear = { viewModel.clearTerminalLogs() },
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }

                    Column(
                        modifier = Modifier
                            .weight(0.55f)
                            .fillMaxHeight()
                    ) {
                        when (state.currentTab) {
                            DewTab.ASSISTANT -> OrcaChatStreamSection(state, viewModel)
                            DewTab.INVENTORY -> InteractiveInventorySection(state, viewModel)
                            DewTab.DOMOTICS -> InteractiveDomoticsSection(state, viewModel) { showLockDialog = true }
                            DewTab.SPANISH_GOV -> InteractiveSpanishGovSection(state, viewModel)
                            DewTab.PRIVACY -> InteractivePrivacySection(state, viewModel)
                        }
                    }
                }
            } else {
                // Diseño Vertical Optimizado para Tablet Vertical y Móviles
                Column(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    OrcaPromptAndQuickBar(
                        state = state,
                        inputText = inputText,
                        onInputChange = { inputText = it },
                        onSend = {
                            if (inputText.isNotBlank()) {
                                viewModel.onUserUtterance(inputText)
                                inputText = ""
                            }
                        },
                        onQuickCommand = { cmd -> viewModel.onUserUtterance(cmd) }
                    )

                    if (state.showTerminalDrawer) {
                        if (state.currentTab == DewTab.ASSISTANT) {
                            OrcaLiveTerminalCard(
                                state = state,
                                onFilterChange = { viewModel.setTerminalFilter(it) },
                                onClear = { viewModel.clearTerminalLogs() },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .heightIn(min = 140.dp, max = 195.dp)
                            )
                        } else {
                            val lastLog = state.terminalLogs.lastOrNull()
                            if (lastLog != null) {
                                Surface(
                                    color = TerminalBg,
                                    shape = RoundedCornerShape(8.dp),
                                    border = BorderStroke(1.dp, EmeraldAccent.copy(alpha = 0.4f)),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text(
                                        text = "dew@local:~# ${lastLog.timestamp} [${lastLog.tag}] ${lastLog.message}",
                                        color = EmeraldAccent,
                                        fontFamily = FontFamily.Monospace,
                                        fontSize = 11.sp,
                                        maxLines = 2,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                                    )
                                }
                            }
                        }
                    }

                    Box(modifier = Modifier.weight(1f)) {
                        when (state.currentTab) {
                            DewTab.ASSISTANT -> OrcaChatStreamSection(state, viewModel)
                            DewTab.INVENTORY -> InteractiveInventorySection(state, viewModel)
                            DewTab.DOMOTICS -> InteractiveDomoticsSection(state, viewModel) { showLockDialog = true }
                            DewTab.SPANISH_GOV -> InteractiveSpanishGovSection(state, viewModel)
                            DewTab.PRIVACY -> InteractivePrivacySection(state, viewModel)
                        }
                    }
                }
            }
        }
    }
}

// =============================================================================
// CABECERA Y BARRA DE NAVEGACIÓN ESTILO ORCA TERMINAL
// =============================================================================
@Composable
private fun OrcaCommandHeader(
    state: DewUiState,
    onToggleTerminal: () -> Unit,
    onToggleOffline: () -> Unit
) {
    Surface(
        color = Color(0xFF0B1120),
        border = BorderStroke(1.dp, BorderSlate),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = Modifier.weight(1f),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                // Icono Oficial Orca·Dew integrado en la cabecera
                Surface(
                    color = Color(0xFF063B32),
                    shape = RoundedCornerShape(10.dp),
                    border = BorderStroke(1.5.dp, CyanAccent)
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "💧>_",
                            color = EmeraldAccent,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 14.sp
                        )
                    }
                }
                Column {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            text = "ORCA·DEW",
                            color = EmeraldAccent,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 16.sp
                        )
                        Surface(
                            color = Color(0xFF064E3B),
                            shape = RoundedCornerShape(6.dp)
                        ) {
                            Text(
                                text = "${"%.0f".format(state.detectedRamGb)}GB · ${state.activeTier.quantization} · MODO ABIERTO",
                                color = Color(0xFFA7F3D0),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "${state.activeTier.tierId} · Preguntas Generales + Control del Hogar",
                        color = TextMuted,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(
                    onClick = onToggleTerminal,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    border = BorderStroke(1.dp, if (state.showTerminalDrawer) CyanAccent else BorderSlate)
                ) {
                    Text(
                        text = if (state.showTerminalDrawer) ">_ TTY ON" else ">_ TTY OFF",
                        color = if (state.showTerminalDrawer) CyanAccent else TextMuted,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                OutlinedButton(
                    onClick = onToggleOffline,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    border = BorderStroke(1.dp, if (state.isOfflineMode) AmberThink else EmeraldAccent)
                ) {
                    Text(
                        text = if (state.isOfflineMode) "AVIÓN" else "LAN OK",
                        color = if (state.isOfflineMode) AmberThink else EmeraldAccent,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}

@Composable
private fun OrcaBottomNavigationBar(
    currentTab: DewTab,
    onSelectTab: (DewTab) -> Unit
) {
    Surface(
        color = Color(0xFF0B1120),
        border = BorderStroke(1.dp, BorderSlate)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 6.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceEvenly
        ) {
            DewTab.entries.forEach { tab ->
                val selected = currentTab == tab
                Surface(
                    color = if (selected) Color(0xFF064E3B) else Color.Transparent,
                    shape = RoundedCornerShape(10.dp),
                    border = if (selected) BorderStroke(1.dp, EmeraldAccent) else null,
                    modifier = Modifier
                        .weight(1f)
                        .padding(horizontal = 2.dp)
                        .clickable { onSelectTab(tab) }
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.padding(vertical = 8.dp, horizontal = 4.dp)
                    ) {
                        Text(
                            text = "[${tab.badgeCode}]",
                            color = if (selected) EmeraldAccent else TextMuted,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            text = tab.title,
                            color = if (selected) TextPrimary else TextMuted,
                            fontSize = 11.sp,
                            fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium
                        )
                    }
                }
            }
        }
    }
}

// =============================================================================
// BARRA DE COMANDOS Y CHIPS DE EJECUCIÓN RÁPIDA + TERMINAL ORCA EN VIVO
// =============================================================================
@Composable
private fun OrcaPromptAndQuickBar(
    state: DewUiState,
    inputText: String,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onQuickCommand: (String) -> Unit
) {
    state.chemicalSafetyAlert?.let { alert ->
        Card(
            colors = CardDefaults.cardColors(containerColor = Color(0xFF450A0A)),
            border = BorderStroke(1.5.dp, DangerRed),
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(
                text = alert,
                color = Color(0xFFFECACA),
                modifier = Modifier.padding(10.dp),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold
            )
        }
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = CardSlate),
        border = BorderStroke(1.dp, BorderSlate),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "dew>",
                    color = EmeraldAccent,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 14.sp
                )
                OutlinedTextField(
                    value = inputText,
                    onValueChange = onInputChange,
                    modifier = Modifier.weight(1f),
                    placeholder = {
                        Text(
                            "Pregunta cualquier cosa a Dew (ciencia, mates, código, recetas) o controla tu casa...",
                            color = TextMuted,
                            fontSize = 12.sp
                        )
                    },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { if (inputText.isNotBlank()) onSend() }),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = EmeraldAccent,
                        unfocusedBorderColor = BorderSlate,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    )
                )
                Button(
                    onClick = onSend,
                    colors = ButtonDefaults.buttonColors(containerColor = EmeraldAccent),
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 12.dp)
                ) {
                    Text("Preguntar", color = Color(0xFF042F2E), fontWeight = FontWeight.ExtraBold, fontSize = 12.sp)
                }
            }

            if (state.voiceState != VoicePipelineState.IDLE) {
                Spacer(modifier = Modifier.height(6.dp))
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth().height(2.dp),
                    color = EmeraldAccent,
                    trackColor = BorderSlate
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Chips rápidos estilo Orca (Preguntas Normales Abiertas + Órdenes del Hogar)
            val quickPrompts = listOf(
                "🍳 Receta Tortilla Perfecta" to "¿Cómo se hace una tortilla de patatas española perfecta paso a paso?",
                "🧮 Calcular IVA de 350€" to "Calcula el 21% de IVA de 350 euros",
                "🌌 ¿Qué es un agujero negro?" to "Explícame de forma clara qué es un agujero negro y la relatividad",
                "🐍 Código Python" to "Escríbeme una función en Python para ordenar y contar elementos",
                "🏋️ Rutina Gimnasio 4 días" to "Hazme una rutina de entrenamiento de gimnasio de 4 días y nutrición",
                "😄 Cuéntame un chiste" to "Cuéntame un chiste de programación y hogar",
                "🍲 Planificar 5 cenas (35€)" to "Planifícame el menú semanal de 5 cenas para 2 personas con 35 euros aprovechando lo que caduca",
                "💡 Apagar salón" to "Apaga todo el salón",
                "🏛️ Preparar Renta AEAT" to "Ayúdame a preparar el borrador de la declaración de la Renta en Hacienda AEAT",
                "🧪 Test CHEM_GUARD" to "¿Puedo mezclar lejía con amoniaco para limpiar el baño?"
            )
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                quickPrompts.forEach { (label, prompt) ->
                    Surface(
                        color = Color(0xFF1E293B),
                        shape = RoundedCornerShape(99.dp),
                        border = BorderStroke(1.dp, Color(0xFF334155)),
                        modifier = Modifier.clickable { onQuickCommand(prompt) }
                    ) {
                        Text(
                            text = label,
                            color = CyanAccent,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun OrcaLiveTerminalCard(
    state: DewUiState,
    onFilterChange: (String) -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = TerminalBg),
        border = BorderStroke(1.dp, Color(0xFF1E293B)),
        modifier = modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "dew@local:~# trace --stream <think> & tools",
                    color = EmeraldAccent,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp
                )
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("ALL" to "Todo", "THINK" to "<think>", "TOOLS" to "Tools").forEach { (key, label) ->
                        val active = state.terminalFilter == key
                        Text(
                            text = "[$label]",
                            color = if (active) CyanAccent else TextMuted,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.clickable { onFilterChange(key) }
                        )
                    }
                    Text(
                        text = "[Clear]",
                        color = DangerRed,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.clickable { onClear() }
                    )
                }
            }
            Spacer(modifier = Modifier.height(6.dp))
            Divider(color = BorderSlate)
            Spacer(modifier = Modifier.height(6.dp))

            val filteredLogs = state.terminalLogs.filter { entry ->
                when (state.terminalFilter) {
                    "THINK" -> entry.level == LogLevel.THINK || entry.tag == "THINK"
                    "TOOLS" -> entry.level == LogLevel.TOOL || entry.level == LogLevel.SUCCESS || entry.level == LogLevel.DANGER
                    else -> true
                }
            }.reversed()

            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                filteredLogs.forEach { log ->
                    val tagColor = when (log.level) {
                        LogLevel.THINK -> AmberThink
                        LogLevel.TOOL -> CyanAccent
                        LogLevel.SUCCESS -> EmeraldAccent
                        LogLevel.WARN -> AmberThink
                        LogLevel.DANGER -> DangerRed
                        LogLevel.INFO -> Color(0xFF94A3B8)
                    }
                    Text(
                        text = "${log.timestamp} [${log.tag}] ${log.message}",
                        color = tagColor,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        lineHeight = 15.sp
                    )
                }
            }
        }
    }
}

// =============================================================================
// PESTAÑA 1: FLUJO CONVERSACIONAL CON BLOQUES <THINK> Y TOOL CALLS (ORCA STYLE)
// =============================================================================
@Composable
private fun OrcaChatStreamSection(state: DewUiState, viewModel: DewViewModel) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        state.chatHistory.reversed().forEach { msg ->
            key(msg.id) {
                var showThinking by remember { mutableStateOf(true) }
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = if (msg.isUser) Color(0xFF1E293B) else CardSlate
                    ),
                    border = BorderStroke(
                        1.dp,
                        if (msg.isUser) CyanAccent.copy(alpha = 0.5f) else EmeraldAccent.copy(alpha = 0.4f)
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = if (msg.isUser) "👤 TÚ (Usuario)" else "🤖 ORCA·DEW (Qwen3.8-9B Local)",
                                color = if (msg.isUser) CyanAccent else EmeraldAccent,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp
                            )
                            Text(
                                text = msg.metricsLabel ?: msg.timestamp,
                                color = TextMuted,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 10.sp
                            )
                        }

                        // Bloque de pensamiento <think> desplegable estilo Orca / DeepSeek / Qwen
                        if (!msg.thinkingTrace.isNullOrBlank()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Surface(
                                color = TerminalBg,
                                shape = RoundedCornerShape(8.dp),
                                border = BorderStroke(1.dp, AmberThink.copy(alpha = 0.4f)),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { showThinking = !showThinking }
                            ) {
                                Column(modifier = Modifier.padding(8.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween
                                    ) {
                                        Text(
                                            text = "🧠 <think> Razonamiento Interno del Modelo",
                                            color = AmberThink,
                                            fontFamily = FontFamily.Monospace,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold
                                        )
                                        Text(
                                            text = if (showThinking) "[Ocultar ▲]" else "[Ver traza ▼]",
                                            color = TextMuted,
                                            fontFamily = FontFamily.Monospace,
                                            fontSize = 10.sp
                                        )
                                    }
                                    if (showThinking) {
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = msg.thinkingTrace,
                                            color = Color(0xFFFDE68A),
                                            fontFamily = FontFamily.Monospace,
                                            fontSize = 11.sp,
                                            lineHeight = 15.sp
                                        )
                                    }
                                }
                            }
                        }

                        // Llamadas a herramientas deterministas
                        if (msg.toolCallsSummary.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                msg.toolCallsSummary.forEach { call ->
                                    Text(
                                        text = "⚡ [TOOL_EXEC] $call",
                                        color = CyanAccent,
                                        fontFamily = FontFamily.Monospace,
                                        fontSize = 10.sp
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = msg.text,
                            color = TextPrimary,
                            fontSize = 14.sp,
                            lineHeight = 20.sp
                        )
                    }
                }
            }
        }
    }
}

// =============================================================================
// PESTAÑA 2: DESPENSA, PLANIFICADOR FLEXIBLE, OCR TICKETS, EAN-13 Y CESTA
// =============================================================================
@Composable
private fun InteractiveInventorySection(state: DewUiState, viewModel: DewViewModel) {
    var newItemName by remember { mutableStateOf("") }
    var newItemUnit by remember { mutableStateOf("uds") }
    var ocrText by remember { mutableStateOf(state.receiptOcrSample) }
    var allergensInput by remember { mutableStateOf(state.householdAllergens) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // 1. PLANIFICADOR SEMANAL FLEXIBLE (<THINK>)
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, EmeraldAccent.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        "🍲 Planificador Semanal Flexible (<think> 9B)",
                        color = EmeraldAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    Text(
                        "Ajusta tu límite en euros, comensales y supermercado; Dew recalcula el menú y la cesta al instante:",
                        color = TextMuted,
                        fontSize = 12.sp
                    )
                    Spacer(modifier = Modifier.height(10.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        // Control de Comensales
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("Comensales:", color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                            OutlinedButton(
                                onClick = {
                                    viewModel.generateFlexibleMealPlan(state.plannerDiners - 1, state.plannerBudgetEur, state.plannerStore)
                                },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                            ) { Text("-", color = TextPrimary) }
                            Text("${state.plannerDiners}", color = CyanAccent, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                            OutlinedButton(
                                onClick = {
                                    viewModel.generateFlexibleMealPlan(state.plannerDiners + 1, state.plannerBudgetEur, state.plannerStore)
                                },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                            ) { Text("+", color = TextPrimary) }
                        }

                        // Control de Presupuesto en Euros
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("Límite €:", color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                            OutlinedButton(
                                onClick = {
                                    viewModel.generateFlexibleMealPlan(state.plannerDiners, state.plannerBudgetEur - 5.0, state.plannerStore)
                                },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                            ) { Text("-5€", color = TextPrimary, fontSize = 11.sp) }
                            Text("${"%.0f".format(state.plannerBudgetEur)} €", color = AmberThink, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                            OutlinedButton(
                                onClick = {
                                    viewModel.generateFlexibleMealPlan(state.plannerDiners, state.plannerBudgetEur + 5.0, state.plannerStore)
                                },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                            ) { Text("+5€", color = TextPrimary, fontSize = 11.sp) }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        listOf("Mercadona", "Carrefour", "Lidl", "Consum").forEach { store ->
                            val selected = state.plannerStore.equals(store, ignoreCase = true)
                            FilterChip(
                                selected = selected,
                                onClick = {
                                    viewModel.generateFlexibleMealPlan(state.plannerDiners, state.plannerBudgetEur, store)
                                },
                                label = { Text(store, fontSize = 11.sp) }
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = {
                            viewModel.generateFlexibleMealPlan(state.plannerDiners, state.plannerBudgetEur, state.plannerStore)
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = EmeraldAccent),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("⚡ Recalcular Menú 5 Cenas y Cesta con <think>", color = Color(0xFF042F2E), fontWeight = FontWeight.ExtraBold)
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    state.generatedMealPlan.forEach { dayPlan ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 3.dp),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    "• ${dayPlan.day}: ${dayPlan.recipeTitle}",
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Medium
                                )
                                if (dayPlan.usesExpiringItem != null) {
                                    Text(
                                        "   ↳ 🌟 ${dayPlan.usesExpiringItem} (${dayPlan.prepMinutes} min)",
                                        color = AmberThink,
                                        fontSize = 11.sp
                                    )
                                }
                            }
                            Text(
                                "${"%.2f".format(dayPlan.estCostPerPersonEur)} €",
                                color = CyanAccent,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 11.sp
                            )
                        }
                    }
                }
            }
        }

        // 2. INVENTARIO INTERACTIVO (CON BOTONES +, -, CONFIRMAR INCERTIDUMBRE Y AÑADIR)
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, BorderSlate),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        "🧊 Nevera, Despensa y Limpieza (${state.inventory.size} ítems)",
                        color = CyanAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    Spacer(modifier = Modifier.height(8.dp))

                    // Barra para añadir cualquier producto manualmente
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = newItemName,
                            onValueChange = { newItemName = it },
                            modifier = Modifier.weight(1f),
                            placeholder = { Text("Añadir producto (ej. Pechuga de pollo, Tomates)...", fontSize = 12.sp) },
                            singleLine = true
                        )
                        Button(
                            onClick = {
                                if (newItemName.isNotBlank()) {
                                    viewModel.addManualInventoryItem(newItemName, 1.0, newItemUnit, "alimentacion")
                                    newItemName = ""
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CyanAccent)
                        ) {
                            Text("+ Añadir", color = Color(0xFF082F49), fontWeight = FontWeight.Bold)
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    state.inventory.forEach { item ->
                        val isUncertain = item.confidence < 0.70f
                        Surface(
                            color = if (isUncertain) Color(0xFF3B2306) else Color(0xFF1E293B),
                            shape = RoundedCornerShape(10.dp),
                            border = BorderStroke(1.dp, if (isUncertain) AmberThink else BorderSlate),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp)
                        ) {
                            Column(modifier = Modifier.padding(10.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = "${item.name} (${item.qty} ${item.unit})",
                                            color = TextPrimary,
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 13.sp
                                        )
                                        Text(
                                            text = "${item.expiryNote ?: "OK"} · Confianza IA: ${(item.confidence * 100).toInt()}%",
                                            color = if (isUncertain) AmberThink else TextMuted,
                                            fontSize = 11.sp
                                        )
                                    }

                                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                        OutlinedButton(
                                            onClick = { viewModel.adjustInventoryQuantity(item.id, -1.0) },
                                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                                        ) { Text("-", color = TextPrimary) }

                                        OutlinedButton(
                                            onClick = { viewModel.adjustInventoryQuantity(item.id, +1.0) },
                                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                                        ) { Text("+", color = TextPrimary) }

                                        Button(
                                            onClick = { viewModel.addCartItem(item.name, item.estPriceEur.coerceAtLeast(1.50)) },
                                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF064E3B)),
                                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                                        ) {
                                            Text("+Cesta", color = EmeraldAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                        }
                                    }
                                }

                                if (isUncertain) {
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(
                                            onClick = {
                                                viewModel.confirmUncertainInventoryItem(item.id, "Lentejas caseras en táper")
                                            },
                                            colors = ButtonDefaults.buttonColors(containerColor = AmberThink)
                                        ) {
                                            Text("✓ Confirmar: Son Lentejas Caseras", color = Color.Black, fontWeight = FontWeight.Bold, fontSize = 11.sp)
                                        }
                                        OutlinedButton(
                                            onClick = { viewModel.adjustInventoryQuantity(item.id, -99.0) }
                                        ) {
                                            Text("Descartar", color = DangerRed, fontSize = 11.sp)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. CESTA DE COMPRA PROPUESTA (DRAFT_PENDING_REVIEW)
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, if (state.draftCartConfirmed) EmeraldAccent else AmberThink),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    val total = state.draftCartItems.sumOf { it.second }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "🛒 Cesta Borrador (${state.plannerStore})",
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp
                        )
                        Text(
                            text = if (state.draftCartConfirmed) "CONFIRMADA POR TI" else "PENDIENTE DE REVISIÓN",
                            color = if (state.draftCartConfirmed) EmeraldAccent else AmberThink,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))

                    state.draftCartItems.forEachIndexed { idx, (name, price) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 3.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("• $name", color = TextPrimary, fontSize = 13.sp, modifier = Modifier.weight(1f))
                            Text("${"%.2f".format(price)} €", color = CyanAccent, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                "✕",
                                color = DangerRed,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier
                                    .clickable { viewModel.removeCartItem(idx) }
                                    .padding(horizontal = 6.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "Total estimado: ${"%.2f".format(total)} € / Límite: ${"%.2f".format(state.plannerBudgetEur)} €",
                        color = if (total <= state.plannerBudgetEur) EmeraldAccent else DangerRed,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 14.sp
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = { viewModel.confirmDraftCart() },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (state.draftCartConfirmed) Color(0xFF334155) else EmeraldAccent
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = if (state.draftCartConfirmed) "✓ Cesta Aprobada (Pulsa para Editar)" else "✓ Confirmar Cesta para Compra (Sin Pago Automático)",
                            color = if (state.draftCartConfirmed) TextPrimary else Color(0xFF042F2E),
                            fontWeight = FontWeight.ExtraBold
                        )
                    }
                }
            }
        }

        // 4. ESCÁNER OCR DE TICKET DE SUPERMERCADO + ESCÁNER EAN-13 DE ALÉRGENOS
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, BorderSlate),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("🧾 Escáner OCR de Ticket Español (Mercadona / Carrefour / Lidl)", color = CyanAccent, fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(6.dp))
                    OutlinedTextField(
                        value = ocrText,
                        onValueChange = { ocrText = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 5
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Button(
                        onClick = { viewModel.processSpanishReceiptOcr(ocrText) },
                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("📸 Procesar Ticket OCR y Añadir Productos a Nevera", color = Color(0xFF082F49), fontWeight = FontWeight.ExtraBold)
                    }

                    Spacer(modifier = Modifier.height(14.dp))
                    Divider(color = BorderSlate)
                    Spacer(modifier = Modifier.height(10.dp))

                    Text("🔍 Escáner EAN-13 y Guardián de Alérgenos del Hogar", color = AmberThink, fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(4.dp))
                    OutlinedTextField(
                        value = allergensInput,
                        onValueChange = {
                            allergensInput = it
                            viewModel.updateHouseholdAllergens(it)
                        },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Tus alérgenos / ingredientes prohibidos (separados por coma)") },
                        singleLine = true
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = { viewModel.scanBarcodeEan13("8480000107046") },
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF064E3B))
                        ) { Text("🥛 Leche Sin Lactosa (8480000107046)", color = EmeraldAccent, fontSize = 11.sp) }

                        Button(
                            onClick = { viewModel.scanBarcodeEan13("8480000231406") },
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF450A0A))
                        ) { Text("🥜 Crema Cacahuete (8480000231406)", color = Color(0xFFFECACA), fontSize = 11.sp) }

                        Button(
                            onClick = { viewModel.scanBarcodeEan13("8410000810004") },
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF450A0A))
                        ) { Text("🍪 Galletas María (Gluten/Lactosa)", color = Color(0xFFFECACA), fontSize = 11.sp) }
                    }

                    state.lastBarcodeScan?.let { scan ->
                        Spacer(modifier = Modifier.height(8.dp))
                        Surface(
                            color = if (scan.isSafeForHousehold) Color(0xFF064E3B) else Color(0xFF450A0A),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(10.dp)) {
                                Text(
                                    text = scan.message,
                                    color = if (scan.isSafeForHousehold) Color(0xFFA7F3D0) else Color(0xFFFECACA),
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 12.sp
                                )
                                Text(
                                    text = "Ingredientes: ${scan.ingredients}",
                                    color = TextPrimary,
                                    fontSize = 11.sp
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// =============================================================================
// PESTAÑA 3: DOMÓTICA LOCAL INTERACTIVA (SWITCHES, TERMOSTATO, CERRADURA)
// =============================================================================
@Composable
private fun InteractiveDomoticsSection(
    state: DewUiState,
    viewModel: DewViewModel,
    onRequestDoorConfirmation: () -> Unit
) {
    var newDevName by remember { mutableStateOf("") }
    var newDevArea by remember { mutableStateOf("Salón") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, CyanAccent.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(
                        "🏠 Control Domótico Local (Home Assistant LAN · 192.168.1.100:8123)",
                        color = CyanAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    Text(
                        "Pulsa sobre cualquier interruptor, ajusta los grados del termostato o lanza comandos grupales:",
                        color = TextMuted,
                        fontSize = 12.sp
                    )
                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = { viewModel.executeAreaDomoticsCommand("Salón", turnOn = false) },
                            colors = ButtonDefaults.buttonColors(containerColor = AmberThink),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("🌙 Apagar Todo el Salón (Proteger Router)", color = Color.Black, fontWeight = FontWeight.Bold, fontSize = 11.sp)
                        }
                        Button(
                            onClick = { viewModel.executeAreaDomoticsCommand("Salón", turnOn = true) },
                            colors = ButtonDefaults.buttonColors(containerColor = EmeraldAccent),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("☀️ Encender Salón", color = Color(0xFF042F2E), fontWeight = FontWeight.Bold, fontSize = 11.sp)
                        }
                    }
                }
            }
        }

        state.devices.forEach { dev ->
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(
                    1.dp,
                    when {
                        dev.domain == "lock" && !dev.isOn -> DangerRed
                        dev.isOn -> EmeraldAccent
                        else -> BorderSlate
                    }
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "${dev.name} · [${dev.area}]",
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 14.sp
                            )
                            Text(
                                text = "ID: ${dev.entityId} · Estado: ${dev.stateText}",
                                color = if (dev.isOn) EmeraldAccent else TextMuted,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 11.sp
                            )
                        }

                        when (dev.domain) {
                            "lock" -> {
                                Button(
                                    onClick = onRequestDoorConfirmation,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = if (dev.isOn) DangerRed else EmeraldAccent
                                    )
                                ) {
                                    Text(
                                        text = if (dev.isOn) "🔓 Abrir (Biometría)" else "🔒 Bloquear Puerta",
                                        color = if (dev.isOn) Color.White else Color(0xFF042F2E),
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 12.sp
                                    )
                                }
                            }
                            else -> {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    if (dev.domain == "switch") {
                                        OutlinedButton(
                                            onClick = { viewModel.toggleDeviceProtection(dev.entityId) },
                                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
                                        ) {
                                            Text(
                                                text = if (dev.isProtected) "🛡️ Protegido" else "🔓 Desprotegido",
                                                color = if (dev.isProtected) AmberThink else TextMuted,
                                                fontSize = 10.sp
                                            )
                                        }
                                    }
                                    Button(
                                        onClick = { viewModel.toggleSmartDevice(dev.entityId) },
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = if (dev.isOn) EmeraldAccent else Color(0xFF334155)
                                        )
                                    ) {
                                        Text(
                                            text = if (dev.isOn) "ENCENDIDO (Apagar)" else "APAGADO (Encender)",
                                            color = if (dev.isOn) Color(0xFF042F2E) else TextPrimary,
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 11.sp
                                        )
                                    }
                                }
                            }
                        }
                    }

                    // Controles interactivos de temperatura si es un termostato (climate)
                    if (dev.domain == "climate") {
                        Spacer(modifier = Modifier.height(10.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                                OutlinedButton(
                                    onClick = { viewModel.setThermostatTemperature(dev.entityId, dev.temperatureC - 0.5) }
                                ) { Text("- 0.5 °C", color = CyanAccent, fontWeight = FontWeight.Bold) }

                                Text(
                                    text = "${"%.1f".format(dev.temperatureC)} °C",
                                    color = AmberThink,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.ExtraBold,
                                    fontSize = 16.sp,
                                    modifier = Modifier.padding(horizontal = 6.dp)
                                )

                                OutlinedButton(
                                    onClick = { viewModel.setThermostatTemperature(dev.entityId, dev.temperatureC + 0.5) }
                                ) { Text("+ 0.5 °C", color = AmberThink, fontWeight = FontWeight.Bold) }
                            }

                            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                listOf("Eco", "Calor", "Frío").forEach { mode ->
                                    FilterChip(
                                        selected = dev.hvacMode == mode,
                                        onClick = { viewModel.setThermostatTemperature(dev.entityId, dev.temperatureC, mode) },
                                        label = { Text(mode, fontSize = 11.sp) }
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // Añadir nuevo dispositivo LAN
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, BorderSlate),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("➕ Registrar Nueva Entidad en Red Local (Home Assistant)", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    Spacer(modifier = Modifier.height(6.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = newDevName,
                            onValueChange = { newDevName = it },
                            modifier = Modifier.weight(1f),
                            placeholder = { Text("Ej. Enchufe Cafetera, Luz Dormitorio...", fontSize = 12.sp) },
                            singleLine = true
                        )
                        OutlinedTextField(
                            value = newDevArea,
                            onValueChange = { newDevArea = it },
                            modifier = Modifier.width(110.dp),
                            placeholder = { Text("Estancia", fontSize = 12.sp) },
                            singleLine = true
                        )
                        Button(
                            onClick = {
                                if (newDevName.isNotBlank()) {
                                    val lowerDev = newDevName.lowercase()
                                    val inferredDomain = when {
                                        lowerDev.contains("termostato") || lowerDev.contains("clima") || lowerDev.contains("calefacc") || lowerDev.contains("aire") -> "climate"
                                        lowerDev.contains("cerradura") || lowerDev.contains("puerta") -> "lock"
                                        lowerDev.contains("enchufe") || lowerDev.contains("cafetera") || lowerDev.contains("router") || lowerDev.contains("switch") -> "switch"
                                        else -> "light"
                                    }
                                    viewModel.addCustomSmartDevice(newDevName, newDevArea, inferredDomain)
                                    newDevName = ""
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CyanAccent)
                        ) {
                            Text("+ Añadir", color = Color(0xFF082F49), fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

// =============================================================================
// PESTAÑA 4: HACIENDA (AEAT), SALUD (17 CCAA) Y TRÁMITES DE ESPAÑA INTERACTIVOS
// =============================================================================
@Composable
private fun InteractiveSpanishGovSection(state: DewUiState, viewModel: DewViewModel) {
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Card(
            colors = CardDefaults.cardColors(containerColor = Color(0xFF1E293B)),
            border = BorderStroke(1.dp, AmberThink),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(
                    "🏛️ Copiloto Soberano de Trámites en España (Nivel 2 - Handoff Oficial)",
                    color = AmberThink,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp
                )
                Text(
                    "Marca los requisitos que ya tienes listos, pulsa «Analizar con <think>» para generar tu informe local y abre la Sede Electrónica oficial en un toque (Dew jamás pide tus claves de Cl@ve).",
                    color = TextPrimary,
                    fontSize = 12.sp
                )
            }
        }

        state.spanishProcedures.forEach { proc ->
            val completedCount = proc.checklist.count { it.checked }
            val totalCount = proc.checklist.size

            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, if (completedCount == totalCount) EmeraldAccent else BorderSlate),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Surface(
                            color = Color(0xFF0C4A6E),
                            shape = RoundedCornerShape(6.dp)
                        ) {
                            Text(
                                text = proc.categoryBadge,
                                color = CyanAccent,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 10.sp,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                            )
                        }
                        Text(
                            text = "Progreso: $completedCount/$totalCount listos",
                            color = if (completedCount == totalCount) EmeraldAccent else AmberThink,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }

                    Spacer(modifier = Modifier.height(6.dp))
                    Text(proc.title, color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    Text("${proc.institution} · App: ${proc.officialAppPackage}", color = TextMuted, fontSize = 11.sp)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(proc.description, color = TextPrimary, fontSize = 12.sp)

                    // Selector de Comunidad Autónoma para Cita Médica
                    if (proc.id == "cita_medica") {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            listOf(
                                "Madrid (SERMAS)",
                                "Cataluña (CatSalut)",
                                "Andalucía (SAS)",
                                "C. Valenciana (GVA)",
                                "País Vasco (Osakidetza)",
                                "Galicia (SERGAS)"
                            ).forEach { reg ->
                                FilterChip(
                                    selected = proc.selectedRegion == reg,
                                    onClick = { viewModel.updateProcedureRegionOrNotes(proc.id, region = reg) },
                                    label = { Text(reg, fontSize = 11.sp) }
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    // Checklist interactivo con toque limpio en toda la fila
                    proc.checklist.forEach { item ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { viewModel.toggleProcedureChecklistItem(proc.id, item.id) }
                                .padding(vertical = 6.dp, horizontal = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Checkbox(
                                checked = item.checked,
                                onCheckedChange = null,
                                colors = CheckboxDefaults.colors(
                                    checkedColor = EmeraldAccent,
                                    uncheckedColor = TextMuted
                                )
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = item.text,
                                color = if (item.checked) EmeraldAccent else TextPrimary,
                                fontSize = 12.sp
                            )
                        }
                    }

                    // Informe IA generado si el usuario pulsó Analizar
                    proc.aiPreparedSummary?.let { summary ->
                        Spacer(modifier = Modifier.height(6.dp))
                        Surface(
                            color = TerminalBg,
                            shape = RoundedCornerShape(8.dp),
                            border = BorderStroke(1.dp, EmeraldAccent.copy(alpha = 0.5f)),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                text = summary,
                                color = Color(0xFFA7F3D0),
                                fontSize = 12.sp,
                                modifier = Modifier.padding(10.dp)
                            )
                        }
                    }

                    var notesInput by remember(proc.id) { mutableStateOf(proc.userNotes) }
                    Spacer(modifier = Modifier.height(6.dp))
                    OutlinedTextField(
                        value = notesInput,
                        onValueChange = {
                            notesInput = it
                            viewModel.updateProcedureRegionOrNotes(proc.id, notes = it)
                        },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Tus notas privadas (síntomas, casillas, matrícula...)") },
                        singleLine = true
                    )

                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = { viewModel.analyzeSpanishProcedureWithAi(proc.id) },
                            colors = ButtonDefaults.buttonColors(containerColor = AmberThink),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("🧠 Analizar con <think>", color = Color.Black, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        }

                        Button(
                            onClick = {
                                val appIntent = context.packageManager.getLaunchIntentForPackage(proc.officialAppPackage)
                                val targetIntent = (appIntent ?: Intent(Intent.ACTION_VIEW, Uri.parse(proc.officialUrl))).apply {
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                try {
                                    context.startActivity(targetIntent)
                                } catch (_: Exception) {
                                    Toast.makeText(
                                        context,
                                        "No se pudo abrir la sede (${proc.officialUrl})",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("🌐 Abrir Sede Oficial", color = Color(0xFF082F49), fontWeight = FontWeight.ExtraBold, fontSize = 12.sp)
                        }
                    }
                }
            }
        }
    }
}

// =============================================================================
// PESTAÑA 5: PRIVACIDAD SOBERANA, MEMORIA SQLCIPHER Y SINCRONIZACIÓN P2P LAN
// =============================================================================
@Composable
private fun InteractivePrivacySection(state: DewUiState, viewModel: DewViewModel) {
    var customKey by remember { mutableStateOf("") }
    var customVal by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Sincronización P2P Familiar en Wi-Fi Local
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, CyanAccent.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("📡 Sincronización P2P Familiar en Wi-Fi (CRDT + PBKDF2-SHA256)", color = CyanAccent, fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(state.lanSyncStatus, color = EmeraldAccent, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = { viewModel.triggerHouseholdLanSync() },
                        colors = ButtonDefaults.buttonColors(containerColor = CyanAccent),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("🔄 Sincronizar Despensa y Cesta en la Wi-Fi del Hogar Ahora", color = Color(0xFF082F49), fontWeight = FontWeight.ExtraBold)
                    }
                }
            }
        }

        // Solicitudes de memoria pendientes de permiso
        if (state.pendingMemoryConsents.isNotEmpty()) {
            run {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF3B2306)),
                    border = BorderStroke(1.dp, AmberThink),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Text("🔔 Permisos Pendientes de Memoria", color = AmberThink, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(6.dp))
                        state.pendingMemoryConsents.forEach { pending ->
                            Text("¿Autorizas recordar «${pending.key}»?", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                            Text(pending.proposedValue, color = Color(0xFFFDE68A), fontSize = 12.sp)
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { viewModel.approveMemoryConsent(pending.id) },
                                    colors = ButtonDefaults.buttonColors(containerColor = EmeraldAccent)
                                ) {
                                    Text("✓ Autorizar en SQLCipher", color = Color(0xFF042F2E), fontWeight = FontWeight.Bold)
                                }
                                OutlinedButton(onClick = { viewModel.rejectMemoryConsent(pending.id) }) {
                                    Text("✕ Rechazar", color = DangerRed)
                                }
                            }
                        }
                    }
                }
            }
        }

        // Memorias aprobadas y formulario para añadir nuevas
        run {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardSlate),
                border = BorderStroke(1.dp, BorderSlate),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("🔒 Lo que Dew sabe de tu hogar (100% en tu RedMagic Astra)", color = EmeraldAccent, fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(8.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = customKey,
                            onValueChange = { customKey = it },
                            modifier = Modifier.weight(0.4f),
                            placeholder = { Text("Clave (ej. Horario)", fontSize = 12.sp) },
                            singleLine = true
                        )
                        OutlinedTextField(
                            value = customVal,
                            onValueChange = { customVal = it },
                            modifier = Modifier.weight(0.6f),
                            placeholder = { Text("Valor (ej. Cenas a las 21:30)", fontSize = 12.sp) },
                            singleLine = true
                        )
                        Button(
                            onClick = {
                                if (customKey.isNotBlank() && customVal.isNotBlank()) {
                                    viewModel.addCustomApprovedMemory(customKey, customVal)
                                    customKey = ""
                                    customVal = ""
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = EmeraldAccent)
                        ) {
                            Text("Guardar", color = Color(0xFF042F2E), fontWeight = FontWeight.Bold)
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    state.approvedMemories.forEach { (k, v) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("• $k", color = CyanAccent, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                Text("  $v", color = TextPrimary, fontSize = 13.sp)
                            }
                            Text(
                                "🗑️ Borrar",
                                color = DangerRed,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier
                                    .clickable { viewModel.removeApprovedMemory(k) }
                                    .padding(6.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(14.dp))
                    Button(
                        onClick = { viewModel.wipeAllMemories() },
                        colors = ButtonDefaults.buttonColors(containerColor = DangerRed),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("🧨 Destrucción Criptográfica Total (Borrar Toda mi Memoria)", color = Color.White, fontWeight = FontWeight.ExtraBold)
                    }
                }
            }
        }
    }
}
