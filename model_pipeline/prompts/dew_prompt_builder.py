#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Constructor de Prompts y Controlador Dinámico de `<think>` para `empero-ai/Qwen3.8-9B-Distill`.
Permite:
  1. Exportar el prefijo fijo de sistema (`dew_system_prefix.txt`) para precomputar la caché KV
     (`dew_system_prompt.session`) durante el empaquetado.
  2. Clasificar en <1 ms si el turno del usuario requiere Modo Rápido (`<think>\\n</think>`)
     o Modo Planificador Profundo (`<think>` abierto).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from model_pipeline.corpus.generate_calibration_corpus import SYSTEM_PROMPT

TurnMode = Literal["fast", "deep_think"]

# Patrones que activan el razonamiento paso a paso (<think> abierto) en el modelo 9B
DEEP_PLANNING_TRIGGERS = re.compile(
    r"\b("
    r"planif[ií]ca\w*|men[uú]\s+semanal|cenas?\s+de\s+la\s+semana|comidas?\s+de\s+la\s+semana|"
    r"organ[ií]za\w*\s+la\s+semana|presupuesto\s+de|cuadrar\s+presupuesto|aprovechar\s+lo\s+que\s+caduca|"
    r"lista\s+de\s+compra\s+semanal|optimiza\w*\s+la\s+cesta"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class BuiltPrompt:
    mode: TurnMode
    full_prompt: str
    grammar_file: str
    max_tokens: int


def classify_turn_mode(user_utterance: str, force_mode: TurnMode | None = None) -> TurnMode:
    """
    Decide si usar el modo instantáneo (<think> cerrado) o el modo pensamiento profundo.
    El 90% de las interacciones cotidianas (voz rápida, inventario, domótica, dudas) van en 'fast'.
    """
    if force_mode is not None:
        return force_mode
    if DEEP_PLANNING_TRIGGERS.search(user_utterance):
        return "deep_think"
    return "fast"


def get_static_system_prefix() -> str:
    """
    Devuelve el prefijo invariable del sistema para precalcular el archivo de sesión KV
    (`llama-cli --prompt-cache dew_system_prompt.session`).
    """
    return f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"


def build_qwen38_prompt(
    user_utterance: str,
    local_context_summary: str,
    force_mode: TurnMode | None = None,
) -> BuiltPrompt:
    mode = classify_turn_mode(user_utterance, force_mode=force_mode)
    sys_prefix = get_static_system_prefix()
    user_turn = (
        f"<|im_start|>user\n"
        f"[Contexto Local: {local_context_summary.strip()}]\n"
        f"Usuario: {user_utterance.strip()}<|im_end|>\n"
    )

    if mode == "fast":
        # Truco clave para empero-ai/Qwen3.8-9B-Distill en voz:
        # cerramos <think>\n</think> para que emita el JSON en el primer token (<0.8s TTFT)
        assistant_prefix = "<|im_start|>assistant\n<think>\n</think>\n"
        return BuiltPrompt(
            mode="fast",
            full_prompt=sys_prefix + user_turn + assistant_prefix,
            grammar_file="dew_fast_turn.gbnf",
            max_tokens=384,
        )
    else:
        # Dejamos <think> abierto para que el 9B razone menús, caducidades y presupuesto
        assistant_prefix = "<|im_start|>assistant\n<think>\n"
        return BuiltPrompt(
            mode="deep_think",
            full_prompt=sys_prefix + user_turn + assistant_prefix,
            grammar_file="dew_deep_think_turn.gbnf",
            max_tokens=896,
        )
