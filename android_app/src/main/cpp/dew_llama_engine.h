#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <mutex>

namespace dew {

/**
 * Parámetros de inicialización de `llama.cpp` optimizados para ejecutar
 * `empero-ai/Qwen3.8-9B-Distill` (arquitectura híbrida Qwen3.5-9B) en móviles de 8 GB y 12 GB+ de RAM.
 */
struct DewModelConfig {
    std::string model_path;
    int32_t n_ctx = 4096;
    std::string type_k = "q8_0";   // Cuantización de claves KV (ahorra ~70% RAM de contexto)
    std::string type_v = "q4_0";   // Cuantización de valores KV
    bool use_mmap = true;          // Obligatorio en 8 GB para permitir paginación del SO
    bool use_mlock = false;        // Nunca bloquear 3,8 GB en RAM física para evitar muertes LMKD
    bool flash_attn = true;        // Aceleración Flash Attention
    int32_t n_threads = 4;
    int32_t n_gpu_layers = 99;     // Delegación Vulkan / OpenCL cuando esté disponible
};

class DewNativeEngine {
public:
    static DewNativeEngine& instance();

    bool initialize_model(const DewModelConfig& config);
    bool load_prompt_cache_session(const std::string& session_path);
    std::string generate_structured_json(
        const std::string& full_chatml_prompt,
        const std::string& gbnf_grammar,
        int32_t max_tokens,
        float temperature
    );
    void release_kv_cache_on_memory_pressure();
    void unload_model();
    bool is_model_loaded() const;
    std::string get_engine_status_json() const;

private:
    DewNativeEngine() = default;
    ~DewNativeEngine();
    DewNativeEngine(const DewNativeEngine&) = delete;
    DewNativeEngine& operator=(const DewNativeEngine&) = delete;

    void unload_model_locked();

    mutable std::mutex mutex_;
    bool model_loaded_ = false;
    bool prompt_cache_loaded_ = false;
    DewModelConfig active_config_{};

#if DEW_HAS_LLAMA_CPP
    bool backend_initialized_ = false;
    struct llama_model* model_ = nullptr;
    struct llama_context* ctx_ = nullptr;
#endif
};

} // namespace dew
