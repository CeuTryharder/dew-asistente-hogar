#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Flexible de Planificación de Comidas y Cesta de Compra Automática (`Meal & Cart Planner`).

Diseñado con máxima flexibilidad para cada hogar:
  - El usuario define libremente su presupuesto límite en euros (`weekly_budget_limit_eur`,
    o `None` si no desea límite), el número de comensales (`diners_count`), los días a planificar,
    el tiempo máximo de cocina para cada día de la semana (`max_prep_minutes_by_day`), sus
    restricciones alimentarias (`dietary_restrictions`) y cualquier ingrediente que evite (`excluded_ingredients`).
  - Soporta que el usuario añada sus propias recetas caseras a la base de datos local.
  - Cruza el plan con el inventario real de la nevera/despensa: prioriza los alimentos próximos
    a caducar y descuenta las existencias actuales para añadir a la cesta SOLO lo que falta,
    utilizando primero los precios reales de los últimos tickets del propio usuario.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dew_core.inventory_and_shopping import InventoryAndShoppingEngine
from dew_core.storage_and_memory import DewLocalStorage, utc_now_iso


@dataclass
class HouseholdPlanningConfig:
    """Configuración 100% personalizable por cada usuario u hogar."""
    diners_count: int = 2
    weekly_budget_limit_eur: Optional[float] = None  # Ej: 35.0, 80.0 o None (sin límite fijo)
    preferred_store: str = "Tu supermercado habitual"
    days_to_plan: List[str] = field(
        default_factory=lambda: ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    )
    max_prep_minutes_by_day: Dict[str, int] = field(default_factory=dict)
    default_max_prep_minutes: int = 30
    dietary_restrictions: List[str] = field(default_factory=list)  # Ej: ['sin_lactosa', 'sin_gluten', 'vegetariano']
    excluded_ingredients: List[str] = field(default_factory=list)  # Ej: ['cilantro', 'picante']
    include_low_stock_cleaning_items: bool = True


@dataclass
class RecipeIngredient:
    name: str
    qty_per_person: float
    unit: str
    reference_unit_price_eur: float


@dataclass
class HouseholdRecipe:
    recipe_id: str
    title: str
    prep_minutes: int
    tags: List[str]  # Ej: ['sin_lactosa', 'sin_gluten', 'vegetariano', 'rapido']
    ingredients: List[RecipeIngredient]


DEFAULT_SPANISH_RECIPES: List[HouseholdRecipe] = [
    HouseholdRecipe(
        recipe_id="crema_calabacin_queso",
        title="Crema suave de calabacín con dados de queso fresco",
        prep_minutes=20,
        tags=["sin_lactosa", "sin_gluten", "vegetariano", "ligero"],
        ingredients=[
            RecipeIngredient("Calabacín", 0.25, "kg", 1.89),
            RecipeIngredient("Queso fresco sin lactosa", 0.5, "tarrina 250g", 1.45),
            RecipeIngredient("Aceite de oliva virgen extra", 0.02, "litros", 7.80),
        ],
    ),
    HouseholdRecipe(
        recipe_id="tortilla_pavo_express",
        title="Tortilla francesa jugosa de pechuga de pavo y calabacín",
        prep_minutes=10,
        tags=["sin_lactosa", "sin_gluten", "rapido", "proteico"],
        ingredients=[
            RecipeIngredient("Huevos camperos", 2.0, "unidades", 0.25),
            RecipeIngredient("Pechuga de pavo en lonchas", 0.5, "envase", 2.15),
        ],
    ),
    HouseholdRecipe(
        recipe_id="garbanzos_espinacas_huevo",
        title="Salteado mediterráneo de garbanzos con espinacas frescas y huevo",
        prep_minutes=15,
        tags=["sin_lactosa", "sin_gluten", "vegetariano", "legumbres"],
        ingredients=[
            RecipeIngredient("Garbanzo cocido", 0.5, "bote_400g", 0.85),
            RecipeIngredient("Espinacas frescas", 0.5, "bolsa", 1.50),
            RecipeIngredient("Huevos camperos", 1.0, "unidades", 0.25),
        ],
    ),
    HouseholdRecipe(
        recipe_id="ensalada_templada_atun",
        title="Ensalada templada rápida de tomate, garbanzos y atún",
        prep_minutes=8,
        tags=["sin_lactosa", "sin_gluten", "rapido", "verano"],
        ingredients=[
            RecipeIngredient("Tomate ensalada", 0.25, "kg", 2.20),
            RecipeIngredient("Atún en aceite de oliva", 1.0, "lata", 1.15),
            RecipeIngredient("Garbanzo cocido", 0.5, "bote_400g", 0.85),
        ],
    ),
    HouseholdRecipe(
        recipe_id="merluza_horno_verduras",
        title="Lomos de merluza al horno con tomate y brócoli",
        prep_minutes=25,
        tags=["sin_lactosa", "sin_gluten", "pescado", "ligero"],
        ingredients=[
            RecipeIngredient("Filetes de merluza", 0.20, "kg", 9.90),
            RecipeIngredient("Brócoli fresco", 0.25, "kg", 1.65),
            RecipeIngredient("Tomate ensalada", 0.20, "kg", 2.20),
        ],
    ),
    HouseholdRecipe(
        recipe_id="pollo_plancha_ensalada",
        title="Pechuga de pollo a la plancha con tomate aliñado",
        prep_minutes=12,
        tags=["sin_lactosa", "sin_gluten", "rapido", "proteico"],
        ingredients=[
            RecipeIngredient("Pechuga de pollo", 0.20, "kg", 6.80),
            RecipeIngredient("Tomate ensalada", 0.20, "kg", 2.20),
        ],
    ),
]


class FlexibleMealPlanner:
    """
    Planificador determinista de comidas y cesta de compra adaptable a las preferencias
    y presupuesto de cualquier usuario.
    """

    def __init__(self, storage: DewLocalStorage, inventory_engine: InventoryAndShoppingEngine) -> None:
        self.storage = storage
        self.inventory = inventory_engine
        self._init_custom_recipes_table()

    def _init_custom_recipes_table(self) -> None:
        self.storage.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_custom_recipes (
                recipe_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                prep_minutes INTEGER NOT NULL,
                tags_json TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.storage.conn.commit()

    def register_custom_recipe(self, recipe: HouseholdRecipe) -> None:
        """Permite al usuario guardar sus propias recetas favoritas en su móvil."""
        self.storage.conn.execute(
            """
            INSERT INTO user_custom_recipes (recipe_id, title, prep_minutes, tags_json, ingredients_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(recipe_id) DO UPDATE SET
                title = excluded.title,
                prep_minutes = excluded.prep_minutes,
                tags_json = excluded.tags_json,
                ingredients_json = excluded.ingredients_json
            """,
            (
                recipe.recipe_id,
                recipe.title,
                recipe.prep_minutes,
                json.dumps(recipe.tags, ensure_ascii=False),
                json.dumps([vars(i) for i in recipe.ingredients], ensure_ascii=False),
                utc_now_iso(),
            ),
        )
        self.storage.conn.commit()

    def get_all_available_recipes(self) -> List[HouseholdRecipe]:
        custom_rows = self.storage.conn.execute("SELECT * FROM user_custom_recipes").fetchall()
        custom_recipes: List[HouseholdRecipe] = []
        for r in custom_rows:
            ings = [RecipeIngredient(**i) for i in json.loads(r["ingredients_json"])]
            custom_recipes.append(
                HouseholdRecipe(
                    recipe_id=r["recipe_id"],
                    title=r["title"],
                    prep_minutes=int(r["prep_minutes"]),
                    tags=json.loads(r["tags_json"]),
                    ingredients=ings,
                )
            )
        return custom_recipes + list(DEFAULT_SPANISH_RECIPES)

    def load_config_from_user_memories(
        self, override_config: Optional[HouseholdPlanningConfig] = None
    ) -> HouseholdPlanningConfig:
        """
        Construye la configuración de planificación leyendo las preferencias que el usuario
        haya guardado en su memoria local, o aplica los valores personalizados que pase en el momento.
        """
        if override_config is not None:
            return override_config

        cfg = HouseholdPlanningConfig()
        memories = {m["key"].lower(): m["value"] for m in self.storage.list_all_memories()}

        if "comensales" in memories:
            try:
                cfg.diners_count = max(1, int(memories["comensales"].split()[0]))
            except (ValueError, IndexError):
                pass

        if "presupuesto_semanal_eur" in memories:
            try:
                val = memories["presupuesto_semanal_eur"].replace("€", "").replace(",", ".").strip()
                cfg.weekly_budget_limit_eur = float(val)
            except ValueError:
                pass

        if "supermercado_habitual" in memories:
            cfg.preferred_store = memories["supermercado_habitual"]

        if "ingredientes_evitados" in memories:
            cfg.excluded_ingredients = [
                x.strip().lower() for x in memories["ingredientes_evitados"].split(",") if x.strip()
            ]

        return cfg

    def generate_plan_and_shopping_cart(
        self, config: Optional[HouseholdPlanningConfig] = None
    ) -> Dict[str, Any]:
        cfg = self.load_config_from_user_memories(config)
        recipes = self.get_all_available_recipes()

        # 1. Consultar inventario actual y alertas de caducidad / stock bajo
        inv_rows = [
            dict(r) for r in self.storage.conn.execute("SELECT * FROM inventory_items").fetchall()
        ]
        stock_by_name: Dict[str, float] = {
            r["normalized_name"].lower(): float(r["qty"]) for r in inv_rows if r["confidence"] >= 0.70
        }
        known_price_by_name: Dict[str, float] = {
            r["normalized_name"].lower(): float(r["last_price_eur"])
            for r in inv_rows
            if r["last_price_eur"] is not None
        }
        alerts = self.inventory.get_low_stock_and_expiring_alerts(within_days=3)
        expiring_names = {i["normalized_name"].lower() for i in alerts["expiring_soon"]}

        # 2. Filtrar recetas compatibles con restricciones y exclusiones del usuario
        compatible_recipes: List[HouseholdRecipe] = []
        for rec in recipes:
            rec_tags_lower = {t.lower() for t in rec.tags}
            if any(req.lower() not in rec_tags_lower for req in cfg.dietary_restrictions):
                continue
            ing_names_lower = " ".join(i.name.lower() for i in rec.ingredients)
            if any(excl.lower() in ing_names_lower for excl in cfg.excluded_ingredients):
                continue
            compatible_recipes.append(rec)

        if not compatible_recipes:
            compatible_recipes = list(recipes)

        # 3. Asignar una receta óptima para cada día solicitado por el usuario
        planned_days: List[Dict[str, Any]] = []
        used_recipe_ids: set[str] = set()
        required_totals: Dict[str, Dict[str, Any]] = {}

        for day_name in cfg.days_to_plan:
            max_mins = cfg.max_prep_minutes_by_day.get(day_name, cfg.default_max_prep_minutes)
            candidates = [r for r in compatible_recipes if r.prep_minutes <= max_mins]
            if not candidates:
                candidates = compatible_recipes

            # Puntuar recetas priorizando: (a) ingredientes que caducan pronto, (b) ingredientes en stock, (c) variedad
            def score_recipe(r: HouseholdRecipe) -> tuple[int, int, int]:
                uses_expiring = sum(1 for ing in r.ingredients if ing.name.lower() in expiring_names)
                uses_in_stock = sum(1 for ing in r.ingredients if stock_by_name.get(ing.name.lower(), 0.0) > 0)
                not_used_yet = 0 if r.recipe_id in used_recipe_ids else 1
                return (not_used_yet, uses_expiring, uses_in_stock)

            candidates.sort(key=score_recipe, reverse=True)
            chosen = candidates[0]
            used_recipe_ids.add(chosen.recipe_id)

            expiring_used = [
                ing.name for ing in chosen.ingredients if ing.name.lower() in expiring_names
            ]
            planned_days.append({
                "day": day_name,
                "recipe_id": chosen.recipe_id,
                "title": chosen.title,
                "prep_minutes": chosen.prep_minutes,
                "diners": cfg.diners_count,
                "uses_expiring_ingredients": expiring_used,
            })

            # Acumular ingredientes escalados por el número de comensales del hogar
            for ing in chosen.ingredients:
                needed_qty = round(ing.qty_per_person * cfg.diners_count, 2)
                key = ing.name.lower()
                if key not in required_totals:
                    required_totals[key] = {
                        "name": ing.name,
                        "needed_qty": 0.0,
                        "unit": ing.unit,
                        "unit_price_eur": known_price_by_name.get(key, ing.reference_unit_price_eur),
                    }
                required_totals[key]["needed_qty"] = round(
                    required_totals[key]["needed_qty"] + needed_qty, 2
                )

        # 4. Calcular faltantes reales descontando lo que ya hay en la nevera/despensa
        shopping_items: List[Dict[str, Any]] = []
        for key, req in required_totals.items():
            available = stock_by_name.get(key, 0.0)
            missing_qty = round(max(0.0, req["needed_qty"] - available), 2)
            if missing_qty > 0:
                units_to_buy = max(1.0, round(missing_qty, 2))
                est_cost = round(units_to_buy * float(req["unit_price_eur"]), 2)
                shopping_items.append({
                    "name": req["name"],
                    "category": "alimentacion",
                    "qty": units_to_buy,
                    "unit": req["unit"],
                    "est_price_eur": est_cost,
                    "reason": f"Falta para menú ({cfg.diners_count} comensales)",
                })

        # 5. Añadir consumibles de limpieza en alerta baja si el usuario lo desea
        if cfg.include_low_stock_cleaning_items:
            for low_item in alerts["low_stock"]:
                if low_item["category"] in ("limpieza", "hogar"):
                    price = float(low_item.get("last_price_eur") or 2.50)
                    shopping_items.append({
                        "name": low_item["normalized_name"],
                        "category": low_item["category"],
                        "qty": 1.0,
                        "unit": low_item["unit"],
                        "est_price_eur": round(price, 2),
                        "reason": f"Stock bajo en casa (quedan {low_item['qty']} {low_item['unit']})",
                    })

        # 6. Generar borrador de cesta con el presupuesto configurado por el usuario
        cart_draft = self.inventory.create_shopping_cart_draft(
            store=cfg.preferred_store,
            items=[
                {
                    "name": i["name"],
                    "category": i["category"],
                    "qty": 1,  # est_price_eur ya incluye el subtotal estimado de la línea
                    "display_qty": f"{i['qty']} {i['unit']}",
                    "est_price_eur": i["est_price_eur"],
                    "reason": i["reason"],
                }
                for i in shopping_items
            ],
            budget_limit_eur=cfg.weekly_budget_limit_eur,
        )

        budget_limit = cfg.weekly_budget_limit_eur
        total_est = cart_draft["estimated_total_eur"]
        budget_diff = round(budget_limit - total_est, 2) if budget_limit is not None else None

        return {
            "config_applied": {
                "diners_count": cfg.diners_count,
                "weekly_budget_limit_eur": budget_limit,
                "preferred_store": cfg.preferred_store,
                "days_planned": len(planned_days),
                "dietary_restrictions": cfg.dietary_restrictions,
                "excluded_ingredients": cfg.excluded_ingredients,
            },
            "meal_plan": planned_days,
            "shopping_cart_draft": cart_draft,
            "budget_summary": {
                "estimated_total_eur": total_est,
                "user_budget_limit_eur": budget_limit,
                "within_budget": cart_draft["within_budget"],
                "remaining_budget_eur": budget_diff,
            },
        }
