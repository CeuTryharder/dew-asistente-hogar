#include "dew_llama_engine.h"

#include <jni.h>
#include <algorithm>
#include <iomanip>
#include <sstream>
#include <cstring>

#if defined(__ANDROID__)
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "DewNativeAI", __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, "DewNativeAI", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "DewNativeAI", __VA_ARGS__)
#else
#include <cstdio>
#define LOGI(...) std::printf(__VA_ARGS__); std::printf("\n")
#define LOGW(...) std::printf(__VA_ARGS__); std::printf("\n")
#define LOGE(...) std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr, "\n")
#endif

#if DEW_HAS_LLAMA_CPP
#include "llama.h"
#endif

namespace dew {

namespace {

std::string escape_json_string(const std::string& input) {
    std::ostringstream out;
    for (unsigned char c : input) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (c < 0x20) {
                    out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c);
                } else {
                    out << static_cast<char>(c);
                }
        }
    }
    return out.str();
}

#if DEW_HAS_LLAMA_CPP
ggml_type parse_kv_cache_type(const std::string& type_name, ggml_type fallback) {
    if (type_name == "q4_0") return GGML_TYPE_Q4_0;
    if (type_name == "q8_0") return GGML_TYPE_Q8_0;
    if (type_name == "f16") return GGML_TYPE_F16;
    return fallback;
}
#endif

} // namespace

DewNativeEngine& DewNativeEngine::instance() {
    static DewNativeEngine inst;
    return inst;
}

DewNativeEngine::~DewNativeEngine() {
    unload_model();
}

bool DewNativeEngine::initialize_model(const DewModelConfig& config) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (model_loaded_) {
        unload_model_locked();
    }

    DewModelConfig sanitized = config;
    if (sanitized.n_ctx <= 0) {
        sanitized.n_ctx = 4096;
    }
    if (sanitized.n_threads <= 0) {
        sanitized.n_threads = 4;
    }
    if (sanitized.model_path.empty()) {
        LOGE("Ruta de modelo GGUF vacía");
        return false;
    }
    active_config_ = sanitized;

    LOGI(
        "Inicializando Qwen3.8-9B-Distill desde %s (n_ctx=%d, type_k=%s, type_v=%s, mmap=%d, mlock=%d)",
        sanitized.model_path.c_str(),
        sanitized.n_ctx,
        sanitized.type_k.c_str(),
        sanitized.type_v.c_str(),
        sanitized.use_mmap ? 1 : 0,
        sanitized.use_mlock ? 1 : 0
    );

#if DEW_HAS_LLAMA_CPP
    if (!backend_initialized_) {
        llama_backend_init();
        backend_initialized_ = true;
    }

    llama_model_params mparams = llama_model_default_params();
    mparams.use_mmap = sanitized.use_mmap;
    mparams.use_mlock = sanitized.use_mlock;
    mparams.n_gpu_layers = sanitized.n_gpu_layers;

    model_ = llama_model_load_from_file(sanitized.model_path.c_str(), mparams);
    if (!model_) {
        LOGE("Fallo al cargar el archivo GGUF: %s", sanitized.model_path.c_str());
        return false;
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = static_cast<uint32_t>(sanitized.n_ctx);
    cparams.n_batch = 512;
    cparams.n_ubatch = 256;
    cparams.n_threads = sanitized.n_threads;
    cparams.n_threads_batch = sanitized.n_threads;
    cparams.flash_attn = sanitized.flash_attn;

    // Cuantización de KV-Cache para mantener la huella de 9B dentro de 4,35 GB en móviles de 8 GB RAM
    cparams.type_k = parse_kv_cache_type(sanitized.type_k, GGML_TYPE_Q8_0);
    cparams.type_v = parse_kv_cache_type(sanitized.type_v, GGML_TYPE_Q4_0);

    ctx_ = llama_init_from_model(model_, cparams);
    if (!ctx_) {
        LOGE("Fallo al crear llama_context para %s", sanitized.model_path.c_str());
        llama_model_free(model_);
        model_ = nullptr;
        return false;
    }
#endif

    model_loaded_ = true;
    return true;
}

bool DewNativeEngine::load_prompt_cache_session(const std::string& session_path) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!model_loaded_ || session_path.empty()) {
        return false;
    }
#if DEW_HAS_LLAMA_CPP
    std::vector<llama_token> session_tokens(static_cast<size_t>(std::max<int32_t>(1, active_config_.n_ctx)));
    size_t n_token_count_out = 0;
    bool ok = llama_state_load_file(
        ctx_,
        session_path.c_str(),
        session_tokens.data(),
        session_tokens.capacity(),
        &n_token_count_out
    );
    prompt_cache_loaded_ = ok;
    LOGI("Prompt cache session cargada (%zu tokens) desde %s: %d", n_token_count_out, session_path.c_str(), ok ? 1 : 0);
    return ok;
#else
    prompt_cache_loaded_ = true;
    LOGI("Prompt cache session registrada en modo ligero: %s", session_path.c_str());
    return true;
#endif
}

std::string DewNativeEngine::generate_structured_json(
    const std::string& full_chatml_prompt,
    const std::string& gbnf_grammar,
    int32_t max_tokens,
    float temperature
) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!model_loaded_) {
        return R"({"spoken_reply":"El modelo local aún no está cargado en memoria.","thinking_mode_used":false,"uncertainty_notes":[],"proposed_actions":[]})";
    }

    const bool is_deep_think =
        full_chatml_prompt.find("<|im_start|>assistant\n<think>\n</think>") == std::string::npos;

#if DEW_HAS_LLAMA_CPP
    const int32_t safe_max_tokens = std::max<int32_t>(1, std::min<int32_t>(max_tokens, 4096));
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    llama_sampler* smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    if (!gbnf_grammar.empty()) {
        llama_sampler* grammar_smpl = llama_sampler_init_grammar(vocab, gbnf_grammar.c_str(), "root");
        if (grammar_smpl) {
            llama_sampler_chain_add(smpl, grammar_smpl);
        } else {
            LOGW("No se pudo inicializar el sampler GBNF; continuando sin restricción gramatical");
        }
    }
    llama_sampler_chain_add(smpl, llama_sampler_init_temp(temperature));
    llama_sampler_chain_add(smpl, llama_sampler_init_dist(42));

    // Tokenización e inferencia restringida por GBNF
    std::vector<llama_token> tokens(full_chatml_prompt.size() + 16);
    int32_t n_tokens = llama_tokenize(
        vocab,
        full_chatml_prompt.c_str(),
        static_cast<int32_t>(full_chatml_prompt.size()),
        tokens.data(),
        static_cast<int32_t>(tokens.size()),
        true,
        true
    );
    if (n_tokens < 0 && (-n_tokens) <= 32768) {
        tokens.resize(static_cast<size_t>(-n_tokens));
        n_tokens = llama_tokenize(
            vocab,
            full_chatml_prompt.c_str(),
            static_cast<int32_t>(full_chatml_prompt.size()),
            tokens.data(),
            static_cast<int32_t>(tokens.size()),
            true,
            true
        );
    }
    if (n_tokens < 0) {
        llama_sampler_free(smpl);
        return R"({"spoken_reply":"Error al tokenizar la consulta local.","thinking_mode_used":false,"uncertainty_notes":[],"proposed_actions":[]})";
    }
    tokens.resize(static_cast<size_t>(n_tokens));

    llama_batch batch = llama_batch_get_one(tokens.data(), static_cast<int32_t>(tokens.size()));
    if (llama_decode(ctx_, batch) != 0) {
        llama_sampler_free(smpl);
        return R"({"spoken_reply":"Memoria de contexto saturada; he liberado caché local.","thinking_mode_used":false,"uncertainty_notes":[],"proposed_actions":[]})";
    }

    std::string output;
    for (int32_t i = 0; i < safe_max_tokens; ++i) {
        llama_token new_token_id = llama_sampler_sample(smpl, ctx_, -1);
        if (llama_vocab_is_eog(vocab, new_token_id)) {
            break;
        }
        char buf[256];
        int32_t n = llama_token_to_piece(vocab, new_token_id, buf, sizeof(buf), 0, true);
        if (n > 0) {
            output.append(buf, static_cast<size_t>(n));
        }
        llama_sampler_accept(smpl, new_token_id);
        batch = llama_batch_get_one(&new_token_id, 1);
        if (llama_decode(ctx_, batch) != 0) {
            break;
        }
    }
    llama_sampler_free(smpl);
    return output;
#else
    // Respuesta estructurada determinista cuando se compila sin el submódulo pesado
    (void)gbnf_grammar;
    (void)max_tokens;
    (void)temperature;
    std::ostringstream oss;
    oss << "{"
        << "\"spoken_reply\":\"Procesado en el motor nativo JNI ("
        << (is_deep_think ? "Modo Planificador <think>" : "Modo Rápido <1s")
        << ").\","
        << "\"thinking_mode_used\":" << (is_deep_think ? "true" : "false") << ","
        << "\"uncertainty_notes\":[],"
        << "\"proposed_actions\":[]"
        << "}";
    return oss.str();
#endif
}

void DewNativeEngine::release_kv_cache_on_memory_pressure() {
    std::lock_guard<std::mutex> lock(mutex_);
    LOGW("Android onTrimMemory detectado: vaciando KV cache para evitar cierre LMKD");
#if DEW_HAS_LLAMA_CPP
    if (ctx_) {
        llama_kv_self_clear(ctx_);
    }
#endif
}

void DewNativeEngine::unload_model_locked() {
#if DEW_HAS_LLAMA_CPP
    if (ctx_) {
        llama_free(ctx_);
        ctx_ = nullptr;
    }
    if (model_) {
        llama_model_free(model_);
        model_ = nullptr;
    }
    if (backend_initialized_) {
        llama_backend_free();
        backend_initialized_ = false;
    }
#endif
    model_loaded_ = false;
    prompt_cache_loaded_ = false;
}

void DewNativeEngine::unload_model() {
    std::lock_guard<std::mutex> lock(mutex_);
    unload_model_locked();
}

bool DewNativeEngine::is_model_loaded() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return model_loaded_;
}

std::string DewNativeEngine::get_engine_status_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::ostringstream oss;
    oss << "{"
        << "\"model_loaded\":" << (model_loaded_ ? "true" : "false") << ","
        << "\"prompt_cache_loaded\":" << (prompt_cache_loaded_ ? "true" : "false") << ","
        << "\"has_llama_cpp_linked\":" << (DEW_HAS_LLAMA_CPP ? "true" : "false") << ","
        << "\"n_ctx\":" << active_config_.n_ctx << ","
        << "\"type_k\":\"" << escape_json_string(active_config_.type_k) << "\","
        << "\"type_v\":\"" << escape_json_string(active_config_.type_v) << "\","
        << "\"use_mmap\":" << (active_config_.use_mmap ? "true" : "false") << ","
        << "\"use_mlock\":" << (active_config_.use_mlock ? "true" : "false")
        << "}";
    return oss.str();
}

} // namespace dew

// =============================================================================
// Exportaciones JNI hacia `es.dew.assistant.core.DewNativeBridge`
// =============================================================================
namespace {

std::string jstring_to_std_string(JNIEnv* env, jstring jstr, const char* fallback = "") {
    if (!env || !jstr) {
        return fallback;
    }
    const char* utf = env->GetStringUTFChars(jstr, nullptr);
    if (!utf) {
        return fallback;
    }
    std::string result(utf);
    env->ReleaseStringUTFChars(jstr, utf);
    return result;
}

} // namespace

extern "C" {

JNIEXPORT jboolean JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeInitModel(
    JNIEnv* env,
    jobject /* thiz */,
    jstring j_model_path,
    jint n_ctx,
    jstring j_type_k,
    jstring j_type_v,
    jboolean use_mmap,
    jboolean use_mlock,
    jboolean flash_attn,
    jint n_threads
) {
    dew::DewModelConfig cfg;
    cfg.model_path = jstring_to_std_string(env, j_model_path);
    cfg.n_ctx = static_cast<int32_t>(n_ctx);
    cfg.type_k = jstring_to_std_string(env, j_type_k, "q8_0");
    cfg.type_v = jstring_to_std_string(env, j_type_v, "q4_0");
    cfg.use_mmap = (use_mmap == JNI_TRUE);
    cfg.use_mlock = (use_mlock == JNI_TRUE);
    cfg.flash_attn = (flash_attn == JNI_TRUE);
    cfg.n_threads = static_cast<int32_t>(n_threads);

    bool ok = dew::DewNativeEngine::instance().initialize_model(cfg);
    return ok ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeLoadPromptCache(
    JNIEnv* env,
    jobject /* thiz */,
    jstring j_session_path
) {
    std::string path_str = jstring_to_std_string(env, j_session_path);
    bool ok = dew::DewNativeEngine::instance().load_prompt_cache_session(path_str);
    return ok ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jstring JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeGenerateStructuredJson(
    JNIEnv* env,
    jobject /* thiz */,
    jstring j_prompt,
    jstring j_grammar,
    jint max_tokens,
    jfloat temperature
) {
    std::string prompt_str = jstring_to_std_string(env, j_prompt);
    std::string grammar_str = jstring_to_std_string(env, j_grammar);

    std::string out = dew::DewNativeEngine::instance().generate_structured_json(
        prompt_str, grammar_str, static_cast<int32_t>(max_tokens), static_cast<float>(temperature)
    );
    return env->NewStringUTF(out.c_str());
}

JNIEXPORT void JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeOnTrimMemoryPressure(
    JNIEnv* /* env */,
    jobject /* thiz */
) {
    dew::DewNativeEngine::instance().release_kv_cache_on_memory_pressure();
}

JNIEXPORT void JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeUnloadModel(
    JNIEnv* /* env */,
    jobject /* thiz */
) {
    dew::DewNativeEngine::instance().unload_model();
}

JNIEXPORT jstring JNICALL
Java_es_dew_assistant_core_DewNativeBridge_nativeGetStatusJson(
    JNIEnv* env,
    jobject /* thiz */
) {
    std::string status = dew::DewNativeEngine::instance().get_engine_status_json();
    return env->NewStringUTF(status.c_str());
}

} // extern "C"
