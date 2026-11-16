package es.dew.assistant.core

/**
 * Puente JNI en Kotlin hacia `libdew_native_ai.so` (`dew_jni_bridge.cpp`).
 * Conecta la aplicación Android con `llama.cpp` para inferencia local de `empero-ai/Qwen3.8-9B-Distill`.
 */
object DewNativeBridge {

    private var nativeLibraryLoaded: Boolean = false

    init {
        try {
            System.loadLibrary("dew_native_ai")
            nativeLibraryLoaded = true
        } catch (e: UnsatisfiedLinkError) {
            nativeLibraryLoaded = false
        }
    }

    fun isNativeLoaded(): Boolean = nativeLibraryLoaded

    fun initModelWithTier(modelPath: String, params: LlamaCppRuntimeParams, nThreads: Int = 4): Boolean {
        if (!nativeLibraryLoaded) return false
        return nativeInitModel(
            jModelPath = modelPath,
            nCtx = params.nCtx,
            jTypeK = params.typeK,
            jTypeV = params.typeV,
            useMmap = params.useMmap,
            useMlock = params.useMlock,
            flashAttn = params.flashAttn,
            nThreads = nThreads
        )
    }

    external fun nativeInitModel(
        jModelPath: String,
        nCtx: Int,
        jTypeK: String,
        jTypeV: String,
        useMmap: Boolean,
        useMlock: Boolean,
        flashAttn: Boolean,
        nThreads: Int
    ): Boolean

    external fun nativeLoadPromptCache(jSessionPath: String): Boolean

    external fun nativeGenerateStructuredJson(
        jPrompt: String,
        jGrammar: String,
        maxTokens: Int,
        temperature: Float
    ): String

    external fun nativeOnTrimMemoryPressure()

    external fun nativeUnloadModel()

    external fun nativeGetStatusJson(): String
}
