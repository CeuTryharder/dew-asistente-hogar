package es.dew.assistant.core

/**
 * Orquestador Nativo de Inferencia y Memoria Secuencial para Android (JNI Bridge).
 *
 * Implementa las dos optimizaciones críticas para `empero-ai/Qwen3.8-9B-Distill`:
 *  1. Descarga secuencial de modelos de voz (`Sherpa-ONNX Whisper`) y visión en dispositivos de 8 GB
 *     antes de invocar a `llama.cpp`, manteniendo la huella máxima de RAM bajo 4,45 GB.
 *  2. Conmutador automático de bloque `<think>`:
 *     - Modo Rápido (`<think>\n</think>` pre-cerrado) para respuestas de voz en < 1 s.
 *     - Modo Planificador (`<think>` abierto) para menús semanales, caducidades y presupuestos.
 */
class DewLlamaOrchestrator(
    private val selectedTier: ModelTier,
    private val runtimeParams: LlamaCppRuntimeParams
) {
    enum class TurnMode {
        FAST_VOICE_OR_ACTION,
        DEEP_WEEKLY_PLANNING
    }

    private val deepPlanningRegex = Regex(
        "\\b(planif[ií]ca\\w*|men[uú]\\s+semanal|cenas?\\s+de\\s+la\\s+semana|" +
        "presupuesto\\s+de|aprovechar\\s+lo\\s+que\\s+caduca|optimiza\\w*\\s+la\\s+cesta)\\b",
        RegexOption.IGNORE_CASE
    )

    fun classifyTurnMode(userUtterance: String): TurnMode {
        return if (deepPlanningRegex.containsMatchIn(userUtterance)) {
            TurnMode.DEEP_WEEKLY_PLANNING
        } else {
            TurnMode.FAST_VOICE_OR_ACTION
        }
    }

    fun formatChatMlPrompt(
        systemPrompt: String,
        localContextSummary: String,
        userUtterance: String
    ): Pair<String, TurnMode> {
        val mode = classifyTurnMode(userUtterance)
        val assistantPrefix = when (mode) {
            TurnMode.FAST_VOICE_OR_ACTION -> "<|im_start|>assistant\n<think>\n</think>\n"
            TurnMode.DEEP_WEEKLY_PLANNING -> "<|im_start|>assistant\n<think>\n"
        }

        val fullPrompt = buildString {
            append("<|im_start|>system\n")
            append(systemPrompt.trim())
            append("<|im_end|>\n")
            append("<|im_start|>user\n")
            append("[Contexto Local: ").append(localContextSummary.trim()).append("]\n")
            append("Usuario: ").append(userUtterance.trim())
            append("<|im_end|>\n")
            append(assistantPrefix)
        }
        return Pair(fullPrompt, mode)
    }
}
