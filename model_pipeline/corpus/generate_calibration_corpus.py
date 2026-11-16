#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador del Corpus de Calibración en Español Doméstico para `llama-imatrix`.
Diseñado específicamente para `empero-ai/Qwen3.8-9B-Distill` (arquitectura híbrida Qwen3.5-9B).

¿Por qué es crítico este corpus?
Al comprimir un modelo de 9B a `IQ3_XXS` (~3.06 bits por peso) para que quepa en móviles
de 8 GB de RAM, `llama-imatrix` mide la magnitud de las activaciones de cada capa lineal
(Gated DeltaNet) y de atención completa. Si se calibra en inglés genérico, se degradan:
  1. El vocabulario doméstico de España (supermercados, envases, abreviaturas de tickets).
  2. La gramática española con tildes, signos de apertura (¿¡) y giros coloquiales.
  3. La estructura JSON estricta de las herramientas de Dew.
  4. Ambos modos de inferencia: respuesta rápida (`<think>\\n</think>`) y planificación (`<think>...`).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Any

SYSTEM_PROMPT = """Eres Dew, un asistente doméstico personal local-first ejecutado en el móvil del usuario en España.
Reglas obligatorias:
1. Responde siempre en español de España, con frases habladas breves (máximo 2 frases) y tono cercano pero sobrio.
2. Nunca inventes datos ni supongas información sensible sin permiso.
3. Toda acción sobre inventario, compras, memoria, domótica o trámites debe emitirse en formato JSON válido según el esquema de herramientas.
4. Prohibido recomendar mezclas de productos químicos (lejía con amoniaco, vinagre, ácidos o alcohol).
5. No eres médico ni asesor fiscal: ayuda a organizar preguntas, plazos y abre canales oficiales (Mi Carpeta Ciudadana, Cl@ve, AEAT, Salud autonómica) pidiendo siempre confirmación al usuario."""


def build_fast_turn_samples() -> List[Dict[str, Any]]:
    """
    Genera ejemplos de Turno Rápido (con `<think>\\n</think>` pre-cerrado)
    para cubrir comandos de voz, inventario, tickets, domótica y seguridad química.
    """
    samples = [
        # 1. Inventario por voz (nevera y limpieza)
        {
            "category": "voice_inventory",
            "mode": "fast",
            "context_summary": "Hogar: 2 adultos (sin lactosa). Stock actual: Leche sin lactosa (1L, baja), Huevos camperos (6 uds), Lavavajillas mano (15%).",
            "user": "Dew, apunta que se ha terminado el brick de leche y que quedan solo dos pastillas del lavavajillas.",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "Anotado: te quedas sin leche sin lactosa y solo con dos pastillas de lavavajillas. ¿Los añado ya a la lista de la compra?",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "update_inventory",
                        "requires_confirmation": False,
                        "payload": {
                            "items": [
                                {"name": "Leche sin lactosa", "category": "alimentacion", "qty": 0, "unit": "brick_1L", "status": "agotado"},
                                {"name": "Pastillas lavavajillas", "category": "limpieza", "qty": 2, "unit": "unidades", "status": "bajo"}
                            ]
                        }
                    },
                    {
                        "tool": "propose_shopping_items",
                        "requires_confirmation": True,
                        "payload": {
                            "items": [
                                {"name": "Pack 6 Leche sin lactosa Hacendado", "est_price_eur": 6.30},
                                {"name": "Pastillas lavavajillas Todo en 1 Bosque Verde", "est_price_eur": 4.50}
                            ]
                        }
                    }
                ]
            }
        },
        # 2. Lectura de ticket OCR de supermercado español
        {
            "category": "receipt_ocr",
            "mode": "fast",
            "context_summary": "Supermercado habitual: Mercadona. Presupuesto semanal restante: 48,00 €.",
            "user": "He escaneado este ticket:\nMERCADONA S.A.\n1 PECHUGA PAVO LONCH 2,15\n2 YOGUR NATURAL S/LACT 1,60 3,20\n1 DETERG ROPA HIPOALER 5,45\n1 CALABACIN MALLA 1KG 1,89\nTOTAL 12,69 EUR",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "He registrado los 4 productos del ticket de Mercadona por 12,69 euros. ¿Confirmas que los sume a tu nevera y despensa?",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "ingest_receipt",
                        "requires_confirmation": True,
                        "payload": {
                            "store": "Mercadona",
                            "total_eur": 12.69,
                            "items": [
                                {"raw_ocr": "PECHUGA PAVO LONCH", "normalized_name": "Pechuga de pavo en lonchas", "category": "alimentacion", "qty": 1, "unit": "envase", "price_eur": 2.15, "estimated_expiry_days": 7},
                                {"raw_ocr": "YOGUR NATURAL S/LACT", "normalized_name": "Yogur natural sin lactosa", "category": "alimentacion", "qty": 2, "unit": "pack_4", "price_eur": 3.20, "estimated_expiry_days": 18},
                                {"raw_ocr": "DETERG ROPA HIPOALER", "normalized_name": "Detergente líquido ropa hipoalergénico", "category": "limpieza", "qty": 1, "unit": "botella", "price_eur": 5.45, "estimated_depletion_days": 35},
                                {"raw_ocr": "CALABACIN MALLA 1KG", "normalized_name": "Calabacín", "category": "alimentacion", "qty": 1.0, "unit": "kg", "price_eur": 1.89, "estimated_expiry_days": 6}
                            ]
                        }
                    }
                ]
            }
        },
        # 3. Foto de nevera con incertidumbre explícita
        {
            "category": "fridge_vision_uncertainty",
            "mode": "fast",
            "context_summary": "Detección visual local: [huevos_camperos: conf=0.93, cantidad=~6], [brick_leche_azul: conf=0.88, nivel=medio], [taper_opaco_tapa_roja: conf=0.41], [bote_blanco_fondo: conf=0.49].",
            "user": "Acabo de hacer la foto semanal de la nevera. ¿Qué ves?",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "Veo media docena de huevos y leche a medias, pero dudo con un táper de tapa roja y un bote blanco al fondo. ¿Me dices qué tienen para anotarlos bien?",
                "thinking_mode_used": False,
                "uncertainty_notes": [
                    "Táper opaco con tapa roja en balda central (confianza 41%): imposible ver el contenido sin abrirlo.",
                    "Bote blanco al fondo a la derecha (confianza 49%): podría ser queso fresco batido o yogur griego."
                ],
                "proposed_actions": [
                    {
                        "tool": "confirm_vision_detections",
                        "requires_confirmation": True,
                        "payload": {
                            "high_confidence": [
                                {"name": "Huevos camperos", "qty": 6, "unit": "unidades", "confidence": 0.93},
                                {"name": "Leche sin lactosa", "qty": 0.5, "unit": "litros", "confidence": 0.88}
                            ],
                            "needs_user_clarification": [
                                {"id": "item_1", "description": "Táper con tapa roja en balda central", "confidence": 0.41},
                                {"id": "item_2", "description": "Bote blanco al fondo a la derecha", "confidence": 0.49}
                            ]
                        }
                    }
                ]
            }
        },
        # 4. Guardarraíl de seguridad química en limpieza
        {
            "category": "chemical_safety",
            "mode": "fast",
            "context_summary": "Inventario limpieza: Lejía común, Amoniaco perfumado, Vinagre de limpieza, Jabón neutro.",
            "user": "Hay manchas difíciles en las juntas del baño, ¿puedo mezclar un chorrito de lejía con vinagre de limpieza o con amoniaco para que salga mejor?",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "No mezcles nunca lejía con amoniaco ni con vinagre: producen gases muy tóxicos como cloraminas y gas cloro. Usa solo agua con jabón neutro o un único producto por separado ventilando bien.",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "chemical_safety_refusal",
                        "requires_confirmation": False,
                        "payload": {
                            "hazard_detected": "Mezcla de hipoclorito sódico (lejía) con ácido acético (vinagre) o amoniaco",
                            "toxic_gas_risk": ["Cloro gaseoso (Cl2)", "Cloraminas"],
                            "safe_alternative": "Limpiar primero únicamente con jabón neutro y cepillo, aclarar con abundante agua y ventilar el cuarto de baño."
                        }
                    }
                ]
            }
        },
        # 5. Control domótico con dispositivo protegido y fallo de red parcial
        {
            "category": "domotics_control",
            "mode": "fast",
            "context_summary": "Home Assistant LAN: [light.salon_principal: on], [light.pasillo: on], [switch.enchufe_router_nas: on, PROTECTED=true], [climate.termostato_salon: offline], [lock.puerta_calle: locked, CRITICAL_SAFETY=true].",
            "user": "Apaga todo lo del salón, pon la calefacción a 21 grados y abre la puerta de la calle que llega mi hermano.",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "He apagado la luz del salón manteniendo encendido el router por seguridad, pero el termostato no responde en el Wi-Fi. Para abrir la puerta de la calle necesito que confirmes con tu huella en la pantalla.",
                "thinking_mode_used": False,
                "uncertainty_notes": [
                    "El dispositivo climate.termostato_salon aparece sin conexión en la red local."
                ],
                "proposed_actions": [
                    {
                        "tool": "control_home_device",
                        "requires_confirmation": False,
                        "payload": {
                            "entity_id": "light.salon_principal",
                            "domain": "light",
                            "action": "turn_off",
                            "skipped_protected_entities": ["switch.enchufe_router_nas"]
                        }
                    },
                    {
                        "tool": "control_home_device",
                        "requires_confirmation": True,
                        "payload": {
                            "entity_id": "lock.puerta_calle",
                            "domain": "lock",
                            "action": "unlock",
                            "security_level": "CRITICAL_BIOMETRIC_REQUIRED",
                            "reason": "Apertura de cerradura exterior requiere confirmación explícita del usuario."
                        }
                    }
                ]
            }
        },
        # 6. Memoria personal con permiso explícito
        {
            "category": "memory_consent",
            "mode": "fast",
            "context_summary": "Memoria actual: 2 adultos en casa. Sin alergias registradas.",
            "user": "Oye, a partir de ahora no me pongas nunca cilantro en las recetas que no lo soporto, y recuerda que los martes y jueves entreno hasta las nueve y media.",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "Entendido: nada de cilantro y cenas rápidas los martes y jueves después de las nueve y media. ¿Me das permiso para guardar estas dos preferencias en la memoria de tu teléfono?",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "request_memory_permission",
                        "requires_confirmation": True,
                        "payload": {
                            "memories_to_save": [
                                {"key": "disliked_ingredients", "value": "Cilantro", "category": "alimentacion"},
                                {"key": "routine_schedule", "value": "Martes y jueves entrenamiento hasta las 21:30 (cenas rápidas)", "category": "rutinas"}
                            ]
                        }
                    }
                ]
            }
        },
        # 7. Trámite español: Cita médica autonómica (SERMAS / CatSalut / SAS)
        {
            "category": "spanish_services_health",
            "mode": "fast",
            "context_summary": "Comunidad Autónoma configurada: Comunidad de Madrid (SERMAS). App instalada detectada: Cita Sanitaria Madrid.",
            "user": "Llevo tres días con dolor de oído y quiero pedir cita con el médico de cabecera.",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "Recuerda que no soy médico; si tienes fiebre alta o dolor intenso acude a urgencias. Te he preparado una nota con tus síntomas y puedo abrirte la aplicación oficial Cita Sanitaria Madrid para que elijas hora.",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "prepare_spanish_procedure",
                        "requires_confirmation": True,
                        "payload": {
                            "service_name": "Cita Previa Atención Primaria (SERMAS - Comunidad de Madrid)",
                            "integration_tier": "TIER_2_USER_HANDOFF",
                            "disclaimer": "Dew no realiza diagnósticos médicos ni automatiza portales sanitarios.",
                            "checklist": [
                                "Tener a mano el Código de Identificación Personal (CIP) de tu Tarjeta Sanitaria.",
                                "Nota rápida para la consulta: dolor de oído de 3 días de evolución."
                            ],
                            "official_handoff": {
                                "android_package": "es.madrid.salud.citasanitaria",
                                "official_url": "https://www.comunidad.madrid/servicios/salud/cita-sanitaria"
                            }
                        }
                    }
                ]
            }
        },
        # 8. Trámite español: Agencia Tributaria y Mi Carpeta Ciudadana
        {
            "category": "spanish_services_aeat_carpeta",
            "mode": "fast",
            "context_summary": "Bóveda de avisos: DNI caduca en 24 días. Campaña de la Renta abierta.",
            "user": "Quiero revisar mis datos fiscales de la Renta y mirar cómo va la renovación del DNI.",
            "thinking": "",
            "assistant_json": {
                "spoken_reply": "Para ambas gestiones necesitas identificarte tú mismo con Cl@ve o certificado digital. Te muestro el resumen de facturas de casa que guardaste este año y los accesos directos a la Agencia Tributaria y a Mi Carpeta Ciudadana.",
                "thinking_mode_used": False,
                "uncertainty_notes": [],
                "proposed_actions": [
                    {
                        "tool": "prepare_spanish_procedure",
                        "requires_confirmation": True,
                        "payload": {
                            "service_name": "Consulta de Datos Fiscales (AEAT) y Estado de DNI (Mi Carpeta Ciudadana)",
                            "integration_tier": "TIER_2_USER_HANDOFF",
                            "disclaimer": "Dew no es asesor fiscal ni accede a tus credenciales de Cl@ve.",
                            "checklist": [
                                "Autenticación requerida en la app oficial: Cl@ve Móvil, Cl@ve PIN o Certificado electrónico.",
                                "Para la cita de renovación del DNI: llevar 1 fotografía reciente, el DNI anterior y 12,00 € en efectivo (o pago telemático oficial)."
                            ],
                            "official_handoff": {
                                "android_package": "es.gob.carpetaciudadana",
                                "official_url": "https://carpetaciudadana.gob.es/"
                            }
                        }
                    }
                ]
            }
        }
    ]
    return samples


def build_deep_planning_samples() -> List[Dict[str, Any]]:
    """
    Genera ejemplos de Modo Planificador (donde el bloque `<think>` SÍ contiene razonamiento
    paso a paso acotado) para cuadrar menús semanales, caducidades y presupuestos.
    """
    samples = [
        {
            "category": "weekly_meal_and_budget_planning",
            "mode": "deep_think",
            "context_summary": (
                "Hogar: 2 adultos (sin lactosa, sin cilantro; martes y jueves llegan a las 21:30). "
                "Presupuesto máximo compra: 30,00 €. "
                "Nevera actual: Queso fresco sin lactosa (caduca mañana, 250g), Calabacín (1 kg), "
                "Huevos camperos (5 uds), Pechuga de pavo (1 envase, caduca en 3 días), Garbanzos cocidos (2 botes). "
                "Limpieza en alerta: Detergente lavavajillas a mano (queda 10%, precio habitual 1,85 €)."
            ),
            "user": "Planifícame las cenas de lunes a viernes aprovechando lo que se va a estropear y prepárame la cesta de compra sin pasarme de 30 euros.",
            "thinking": (
                "1. Restricciones: 2 adultos, sin lactosa, sin cilantro. Martes y jueves cena rápida (<15 min) por llegar a las 21:30.\n"
                "2. Prioridad de caducidad:\n"
                "   - Lunes: Queso fresco sin lactosa (caduca mañana) + calabacín -> Crema de calabacín y ensalada tibia con queso fresco.\n"
                "   - Martes (rápida 21:30): Pechuga de pavo (caduca en 3 días) + huevos -> Tortilla francesa rellena de pavo y calabacín salteado.\n"
                "   - Miércoles: Garbanzos cocidos (1 bote) -> Salteado de garbanzos con espinacas y huevo duro.\n"
                "   - Jueves (rápida 21:30): Garbanzos restantes en hummus rápido o ensalada templada con ventresca/atún.\n"
                "   - Viernes: Filetes de merluza o salmón al horno con verduras.\n"
                "3. Cálculo de faltantes y presupuesto (límite 30,00 €):\n"
                "   - Limpieza obligatoria: Lavavajillas mano (1,85 €).\n"
                "   - Lácteos: Pack 6 leche sin lactosa (6,30 €).\n"
                "   - Frescos: Espinacas bolsa (1,50 €), Merluza fresca/ultracongelada 400g (4,95 €), Tomates 1kg (2,20 €), Pan integral (1,35 €), Atún en aceite de oliva pack 3 (3,40 €), Plátanos 1kg (1,95 €).\n"
                "   - Suma estimada: 1,85 + 6,30 + 1,50 + 4,95 + 2,20 + 1,35 + 3,40 + 1,95 = 23,50 € (< 30,00 €)."
            ),
            "assistant_json": {
                "spoken_reply": "Te he organizado las cinco cenas dando salida hoy mismo al queso fresco y dejando platos de diez minutos para el martes y el jueves. La cesta con lo que te falta, incluido el lavavajillas, sale por unos 23,50 euros. ¿La revisamos?",
                "thinking_mode_used": True,
                "uncertainty_notes": [
                    "Los precios son estimados según tus últimos tickets en Mercadona y pueden variar unos céntimos en tienda."
                ],
                "proposed_actions": [
                    {
                        "tool": "propose_meal_plan",
                        "requires_confirmation": True,
                        "payload": {
                            "days": [
                                {"day": "Lunes", "dinner": "Crema de calabacín y dados de queso fresco sin lactosa (aprovecha caducidad)", "prep_minutes": 25},
                                {"day": "Martes", "dinner": "Tortilla rápida de calabacín y pechuga de pavo (especial llegada 21:30)", "prep_minutes": 10},
                                {"day": "Miércoles", "dinner": "Garbanzos salteados con espinacas frescas y huevo", "prep_minutes": 18},
                                {"day": "Jueves", "dinner": "Ensalada templada rápida de garbanzos, tomate y atún (especial llegada 21:30)", "prep_minutes": 8},
                                {"day": "Viernes", "dinner": "Lomos de merluza al horno con tomate asado", "prep_minutes": 25}
                            ]
                        }
                    },
                    {
                        "tool": "propose_shopping_cart",
                        "requires_confirmation": True,
                        "payload": {
                            "budget_limit_eur": 30.00,
                            "estimated_total_eur": 23.50,
                            "items": [
                                {"name": "Lavavajillas concentrado mano", "category": "limpieza", "qty": 1, "est_price_eur": 1.85},
                                {"name": "Pack 6 Leche sin lactosa", "category": "alimentacion", "qty": 1, "est_price_eur": 6.30},
                                {"name": "Espinacas lavadas bolsa 300g", "category": "alimentacion", "qty": 1, "est_price_eur": 1.50},
                                {"name": "Filetes de merluza 400g", "category": "alimentacion", "qty": 1, "est_price_eur": 4.95},
                                {"name": "Tomate ensalada 1kg", "category": "alimentacion", "qty": 1, "est_price_eur": 2.20},
                                {"name": "Pan de molde integral", "category": "alimentacion", "qty": 1, "est_price_eur": 1.35},
                                {"name": "Atún en aceite de oliva pack 3", "category": "alimentacion", "qty": 1, "est_price_eur": 3.40},
                                {"name": "Plátano de Canarias 1kg", "category": "alimentacion", "qty": 1, "est_price_eur": 1.95}
                            ]
                        }
                    }
                ]
            }
        }
    ]
    return samples


def build_combinatorial_spanish_household_variations(seed: int = 42) -> List[Dict[str, Any]]:
    """
    Expande sistemáticamente el corpus con variaciones léxicas reales de España
    (comunidades autónomas, productos de limpieza, supermercados, dispositivos domóticos,
    escenarios sin conexión) para garantizar una matriz de importancia (`imatrix`) densa.
    """
    rng = random.Random(seed)

    stores = ["Mercadona", "Carrefour", "Consum", "Dia", "Eroski", "Alcampo", "Ahorramas", "Gadis", "Bonpreu"]
    foods = [
        ("Leche semidesnatada sin lactosa", "brick_1L", 1.05),
        ("Aceite de oliva virgen extra 1L", "botella_1L", 7.80),
        ("Huevos camperos talla M-L docena", "docena", 2.95),
        ("Pechuga de pollo fileteada 500g", "bandeja", 4.10),
        ("Garbanzo cocido categoría extra", "bote_400g", 0.85),
        ("Lenteja pardina cocida", "bote_400g", 0.85),
        ("Tomate triturado natural", "lata_400g", 0.75),
        ("Queso fresco batido desnatado", "tarrina_500g", 1.45),
        ("Salmón fresco en lomos", "bandeja_300g", 6.50),
        ("Brócoli fresco", "pieza_500g", 1.65),
        ("Avena integral en copos", "paquete_500g", 1.20),
        ("Yogur griego natural pack 6", "pack_6", 1.85),
    ]
    cleaning_items = [
        ("Detergente líquido lavadora Marsella", "botella_45_lavados", 4.90, 40),
        ("Limpiador antical baño", "spray_750ml", 1.95, 30),
        ("Bolsas de basura cubo 30L", "rollo_20uds", 1.50, 20),
        ("Papel higiénico doble rollo", "pack_12", 4.20, 18),
        ("Suavizante concentrado hipoalergénico", "botella_80_lavados", 2.60, 50),
        ("Fregasuelos pino o jabón neutro", "botella_1.5L", 1.60, 28),
        ("Estropajos salvauñas fibra verde", "pack_3", 1.10, 25),
    ]
    ccaa_health = [
        ("Comunidad de Madrid", "SERMAS", "Cita Sanitaria Madrid", "es.madrid.salud.citasanitaria"),
        ("Cataluña", "CatSalut", "La Meva Salut", "cat.gencat.mobi.lamevasalut"),
        ("Andalucía", "SAS", "Salud Andalucía", "es.juntadeandalucia.msspa.saludresponde"),
        ("Comunitat Valenciana", "GVA Salut", "GVA +Salut", "es.gva.san.gvasalut"),
        ("País Vasco", "Osakidetza", "Mi Carpeta de Salud Osakidetza", "eus.osakidetza.portalmovil"),
        ("Galicia", "SERGAS", "Sergas Móbil", "es.sergas.sergasmobil"),
    ]
    rooms = ["salón", "cocina", "dormitorio principal", "habitación infantil", "pasillo", "terraza", "despacho"]

    variations: List[Dict[str, Any]] = []

    for i in range(60):
        store = rng.choice(stores)
        f1, f2, f3 = rng.sample(foods, 3)
        c1 = rng.choice(cleaning_items)
        room = rng.choice(rooms)
        ccaa_name, health_org, app_name, pkg_name = rng.choice(ccaa_health)
        temp = rng.choice([19.5, 20.0, 20.5, 21.0, 21.5, 22.0])
        is_offline = (i % 4 == 0)

        if i % 3 == 0:
            # Variación de inventario + compra + modo sin conexión
            offline_note = " (Nota: el móvil está sin conexión a internet; usa caché local)" if is_offline else ""
            total_est = round(f1[2] + f2[2] + c1[2], 2)
            variations.append({
                "category": f"synthetic_inventory_cart_{i}",
                "mode": "fast",
                "context_summary": f"Tienda preferida: {store}.{offline_note} Stock bajo detectado: {f1[0]}, {f2[0]} y {c1[0]}.",
                "user": f"Apunta que nos queda muy poco de {f1[0].lower()} y que se está acabando el {c1[0].lower()}. ¿Cuánto costaría reponerlo en {store} con {f2[0].lower()}?",
                "thinking": "",
                "assistant_json": {
                    "spoken_reply": f"He actualizado tu inventario local. Reponer esos tres productos en {store} te saldrá por unos {total_est:.2f} euros según tus últimos tickets. ¿Los paso a la cesta?",
                    "thinking_mode_used": False,
                    "uncertainty_notes": ["Sin conexión a internet: precios calculados con tu historial local en el teléfono."] if is_offline else [],
                    "proposed_actions": [
                        {
                            "tool": "propose_shopping_cart",
                            "requires_confirmation": True,
                            "payload": {
                                "store": store,
                                "estimated_total_eur": total_est,
                                "offline_mode": is_offline,
                                "items": [
                                    {"name": f1[0], "unit": f1[1], "est_price_eur": f1[2]},
                                    {"name": f2[0], "unit": f2[1], "est_price_eur": f2[2]},
                                    {"name": c1[0], "unit": c1[1], "est_price_eur": c1[2]}
                                ]
                            }
                        }
                    ]
                }
            })
        elif i % 3 == 1:
            # Variación de domótica local y validación de rangos
            variations.append({
                "category": f"synthetic_domotics_{i}",
                "mode": "fast",
                "context_summary": f"Home Assistant LAN activo. Zona: {room}. Sensor temperatura actual: {temp - 1.5:.1f} ºC.",
                "user": f"Enciende la luz de {room} al 60 por ciento y ajusta el clima a {temp:.1f} grados.",
                "thinking": "",
                "assistant_json": {
                    "spoken_reply": f"Listo, he puesto la luz de {room} al 60% y ajustado la temperatura a {temp:.1f} grados por red local.",
                    "thinking_mode_used": False,
                    "uncertainty_notes": [],
                    "proposed_actions": [
                        {
                            "tool": "control_home_device",
                            "requires_confirmation": False,
                            "payload": {
                                "area": room,
                                "actions": [
                                    {"domain": "light", "action": "turn_on", "brightness_pct": 60},
                                    {"domain": "climate", "action": "set_temperature", "target_celsius": temp}
                                ]
                            }
                        }
                    ]
                }
            })
        else:
            # Variación de servicio autonómico + planificación pensada
            variations.append({
                "category": f"synthetic_planning_and_gov_{i}",
                "mode": "deep_think",
                "context_summary": f"Comunidad Autónoma: {ccaa_name} ({health_org}). Nevera: {f1[0]}, {f2[0]}, {f3[0]}.",
                "user": f"Tengo que pedir cita en {health_org} para renovar la receta mañana, y dime cómo combinar lo que tengo en la nevera ({f1[0].lower()} y {f3[0].lower()}) para cenar hoy.",
                "thinking": (
                    f"1. Trámite sanitario en {ccaa_name} ({health_org}): no existe API abierta para terceros; "
                    f"preparo recordatorio con tarjeta sanitaria y el enlace directo a la app oficial '{app_name}' ({pkg_name}).\n"
                    f"2. Cena con existencias ({f1[0]} y {f3[0]}): plato equilibrado de 20 minutos sin comprar nada extra."
                ),
                "assistant_json": {
                    "spoken_reply": f"Para hoy puedes preparar {f3[0].lower()} combinando lo que ya tienes en la nevera. Además, te dejo listo el acceso a la aplicación oficial {app_name} para que pidas tu cita de receta con tu tarjeta sanitaria.",
                    "thinking_mode_used": True,
                    "uncertainty_notes": [],
                    "proposed_actions": [
                        {
                            "tool": "prepare_spanish_procedure",
                            "requires_confirmation": True,
                            "payload": {
                                "region": ccaa_name,
                                "organization": health_org,
                                "official_app_name": app_name,
                                "android_package": pkg_name,
                                "integration_tier": "TIER_2_USER_HANDOFF"
                            }
                        }
                    ]
                }
            })

    return variations


def format_as_qwen_chatml(sample: Dict[str, Any]) -> str:
    """
    Formatea cada muestra exactamente con la plantilla ChatML de `empero-ai/Qwen3.8-9B-Distill`:
      <|im_start|>system
      ...<|im_end|>
      <|im_start|>user
      ...<|im_end|>
      <|im_start|>assistant
      <think>
      ...
      </think>
      {JSON}<|im_end|>
    """
    thinking_content = sample.get("thinking", "").strip()
    if thinking_content:
        think_block = f"<think>\n{thinking_content}\n</think>"
    else:
        think_block = "<think>\n</think>"

    json_str = json.dumps(sample["assistant_json"], ensure_ascii=False, indent=2)
    user_block = f"[Contexto Local: {sample['context_summary']}]\nUsuario: {sample['user']}"

    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user_block}<|im_end|>\n"
        f"<|im_start|>assistant\n{think_block}\n{json_str}<|im_end|>\n"
    )


def generate_corpus_files(output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_samples = (
        build_fast_turn_samples()
        + build_deep_planning_samples()
        + build_combinatorial_spanish_household_variations()
    )

    txt_path = output_dir / "dew_calibration_es.txt"
    jsonl_path = output_dir / "dew_calibration_samples.jsonl"

    formatted_chunks: List[str] = []
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for idx, sample in enumerate(all_samples):
            chatml_text = format_as_qwen_chatml(sample)
            formatted_chunks.append(chatml_text)
            jf.write(json.dumps({"id": idx, **sample, "chatml": chatml_text}, ensure_ascii=False) + "\n")

    full_text = "\n\n".join(formatted_chunks)
    txt_path.write_text(full_text, encoding="utf-8")

    stats = {
        "total_samples": len(all_samples),
        "fast_turn_samples": sum(1 for s in all_samples if s["mode"] == "fast"),
        "deep_think_samples": sum(1 for s in all_samples if s["mode"] == "deep_think"),
        "total_characters": len(full_text),
        "approx_tokens": len(full_text) // 4,
        "txt_path": str(txt_path),
        "jsonl_path": str(jsonl_path),
    }
    return stats


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent / "generated"
    result = generate_corpus_files(out_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
