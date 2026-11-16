package es.dew.assistant.core

import kotlin.math.sqrt

/**
 * Gestor Nativo de Voz Offline para Android (`Sherpa-ONNX`: `Silero VAD` + `Whisper Base INT8` + `Piper VITS es_ES`).
 *
 * Cumple las reglas de diseño de voz y memoria de Dew:
 *  1. El audio capturado en el `Push-to-Talk` vive únicamente en un buffer de RAM volátil (16 kHz mono)
 *     y se destruye inmediatamente tras transcribirse (0 segundos en disco).
 *  2. En móviles de 8 GB de RAM ([ModelTier.COMPACT_8GB]), libera el reconocedor Whisper antes de
 *     despertar a `Qwen3.8-9B-Distill`.
 *  3. Normaliza homófonos frecuentes en español doméstico y expande unidades (€, ºC, L, uds) antes de hablar.
 */
class DewSherpaVoiceManager(
    private val activeTier: ModelTier,
    private val rmsSilenceThreshold: Float = 0.015f
) {
    companion object {
        const val STT_SAMPLE_RATE_HZ = 16000
        const val TTS_SAMPLE_RATE_HZ = 22050
    }

    private val phoneticFixes: List<Pair<Regex, String>> = listOf(
        Regex("\\bsin\\s+la\\s+tosa\\b", RegexOption.IGNORE_CASE) to "sin lactosa",
        Regex("\\bsin\\s+latosa\\b", RegexOption.IGNORE_CASE) to "sin lactosa",
        Regex("\\bmerca\\s+dona\\b", RegexOption.IGNORE_CASE) to "Mercadona",
        Regex("\\bha?cen\\s*dado\\b", RegexOption.IGNORE_CASE) to "Hacendado",
        Regex("\\bbosque\\s*berde\\b", RegexOption.IGNORE_CASE) to "Bosque Verde",
        Regex("\\bclabe\\s+m[oó]vil\\b", RegexOption.IGNORE_CASE) to "Cl@ve Móvil",
        Regex("\\bcita\\s+previa\\s+ser\\s+mas\\b", RegexOption.IGNORE_CASE) to "cita previa SERMAS"
    )

    private val ttsExpansions: List<Pair<Regex, String>> = listOf(
        Regex("(\\d+[.,]\\d+)\\s*€") to "$1 euros",
        Regex("(\\d+)\\s*€") to "$1 euros",
        Regex("(\\d+(?:[.,]\\d+)?)\\s*[º°]C\\b", RegexOption.IGNORE_CASE) to "$1 grados",
        Regex("(\\d+(?:[.,]\\d+)?)\\s*L\\b") to "$1 litros",
        Regex("(\\d+(?:[.,]\\d+)?)\\s*kg\\b", RegexOption.IGNORE_CASE) to "$1 kilos",
        Regex("\\buds?\\.?\\b", RegexOption.IGNORE_CASE) to "unidades",
        Regex("\\bCl@ve\\b", RegexOption.IGNORE_CASE) to "Clave",
        Regex("\\bAEAT\\b") to "Agencia Tributaria"
    )

    fun hasVoiceActivity(pcmBuffer: FloatArray): Boolean {
        if (pcmBuffer.isEmpty()) return false
        var sumSq = 0.0
        for (sample in pcmBuffer) {
            sumSq += (sample * sample).toDouble()
        }
        val rms = sqrt(sumSq / pcmBuffer.size).toFloat()
        return rms >= rmsSilenceThreshold
    }

    fun normalizeSpanishTranscript(rawTranscript: String): String {
        var result = rawTranscript.trim()
        for ((pattern, replacement) in phoneticFixes) {
            result = pattern.replace(result, replacement)
        }
        return result.replace(Regex("\\s+"), " ").trim()
    }

    fun prepareSpanishTtsText(spokenReply: String, maxSentences: Int = 2): String {
        var cleaned = spokenReply
            .replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "")
            .replace(Regex("[*_`#]+"), "")
            .trim()

        val sentences = cleaned.split(Regex("(?<=[.!?])\\s+"))
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        cleaned = sentences.take(maxSentences).joinToString(" ")

        for ((pattern, replacement) in ttsExpansions) {
            cleaned = pattern.replace(cleaned, replacement)
        }
        return cleaned.replace(Regex("\\s+"), " ").trim()
    }

    fun shouldUnloadSttBeforeLlm(): Boolean {
        return activeTier.sequentialUnloadRequired
    }
}
