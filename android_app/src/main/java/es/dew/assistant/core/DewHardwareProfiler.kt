package es.dew.assistant.core

import android.app.ActivityManager
import android.content.Context
import kotlin.math.roundToInt

/**
 * Perfilador de Hardware de Dew para Android.
 * Detecta la memoria RAM física total del dispositivo y selecciona entre las dos variantes
 * calibradas en español de `empero-ai/Qwen3.8-9B-Distill`:
 *  - [ModelTier.COMPACT_8GB]: `IQ3_XXS` (~3,75 GB, con `imatrix` y tensores `q4_k`/`q5_k`)
 *  - [ModelTier.PRO_12GB]: `Q4_K_M` (~5,30 GB, con `imatrix` y tensores `q5_k`/`q6_k`)
 */
enum class ModelTier(
    val tierId: String,
    val ggufFileName: String,
    val quantization: String,
    val estimatedDownloadMb: Int,
    val sequentialUnloadRequired: Boolean
) {
    COMPACT_8GB(
        tierId = "DEW_9B_COMPACT_8GB",
        ggufFileName = "dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf",
        quantization = "IQ3_XXS (imatrix-ES)",
        estimatedDownloadMb = 3840,
        sequentialUnloadRequired = true
    ),
    PRO_12GB(
        tierId = "DEW_9B_PRO_12GB",
        ggufFileName = "dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf",
        quantization = "Q4_K_M (imatrix-ES)",
        estimatedDownloadMb = 5420,
        sequentialUnloadRequired = false
    )
}

data class LlamaCppRuntimeParams(
    val nCtx: Int = 4096,
    val typeK: String = "q8_0",
    val typeV: String = "q4_0",
    val useMmap: Boolean = true,
    val useMlock: Boolean = false,
    val flashAttn: Boolean = true,
    val nBatch: Int = 512,
    val nUbatch: Int = 256
)

object DewHardwareProfiler {

    fun getTotalDeviceRamGb(context: Context): Double {
        val actManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        actManager.getMemoryInfo(memInfo)
        return memInfo.totalMem.toDouble() / (1024.0 * 1024.0 * 1024.0)
    }

    fun selectOptimalTier(totalRamGb: Double): ModelTier {
        return when {
            totalRamGb >= 11.5 -> ModelTier.PRO_12GB
            totalRamGb >= 7.0 -> ModelTier.COMPACT_8GB
            else -> ModelTier.COMPACT_8GB // Fallback con descarga agresiva de KV cache
        }
    }

    fun buildRuntimeParams(tier: ModelTier, totalRamGb: Double = 16.0): LlamaCppRuntimeParams {
        val is16GbFlagshipTablet = totalRamGb >= 14.5
        return LlamaCppRuntimeParams(
            nCtx = if (is16GbFlagshipTablet) 8192 else 4096,
            typeK = "q8_0",
            typeV = if (is16GbFlagshipTablet) "q8_0" else "q4_0",
            useMmap = true,
            useMlock = false,
            flashAttn = true,
            nBatch = if (is16GbFlagshipTablet) 1024 else 512,
            nUbatch = if (tier == ModelTier.COMPACT_8GB) 256 else 512
        )
    }
}
