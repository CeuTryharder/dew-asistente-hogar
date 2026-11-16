---
license: apache-2.0
base_model: empero-ai/Qwen3.8-9B-Distill
language:
  - es
  - en
tags:
  - gguf
  - mobile
  - android
  - ios
  - llama.cpp
  - imatrix
  - spanish
  - dew-assistant
pipeline_tag: text-generation
---

# CeuTryharder/Dew-Qwen3.8-9B-Mobile-ES-GGUF — Pesos Móviles Calibrados en Español para Dew

Este repositorio contiene las dos ediciones móviles cuantizadas con **Matriz de Importancia (`imatrix`) calibrada en español doméstico** a partir de [`empero-ai/Qwen3.8-9B-Distill`](https://huggingface.co/empero-ai/Qwen3.8-9B-Distill) (licencia **Apache 2.0**):

| Archivo GGUF | Teléfono Objetivo | Cuantización Cuerpo | Tensores Protegidos | Tamaño Aprox. | RAM en Ejecución (KV 4k `q8_0`/`q4_0`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `dew-qwen3.8-9b-compact-8gb-iq3_xxs-es.gguf` | **Móviles de 8 GB RAM** | `IQ3_XXS` (3.06 bpw) | `token_embd=q4_k`, `output=q5_k` | ~3,75 GB | ~4,35 GB (`mmap` activo) |
| `dew-qwen3.8-9b-pro-12gb-q4_k_m-es.gguf` | **Móviles de 12 GB+ RAM** | `Q4_K_M` (4.85 bpw) | `token_embd=q5_k`, `output=q6_k` | ~5,30 GB | ~6,10 GB (`mmap` activo) |

## Conmutador de Latencia Cero (`<think>` Switch)
* **Modo Voz Rápida (<1s TTFT):** Inyectar `<|im_start|>assistant\n<think>\n</think>\n` junto con `dew_fast_turn.gbnf`.
* **Modo Planificador Semanal:** Inyectar `<|im_start|>assistant\n<think>\n` junto con `dew_deep_think_turn.gbnf`.
