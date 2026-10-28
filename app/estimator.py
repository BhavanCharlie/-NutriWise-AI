"""The main entry point: turn a meal description into a NutritionEstimate.

    estimate_meal("2 rotis and dal")  -> always returns a NutritionEstimate

Stages run cheapest and most reliable first; the first one that returns an
estimate wins:
    1. local food table   (instant, offline)
    2. nutrition APIs     (real databases, needs network)
    3. LLMs               (handles anything, slowest, least exact)
    4. placeholder        (rough guess so the app never crashes)
"""

import logging
import time

from app.apis import estimate_from_apis
from app.food_table import estimate_from_table, parse_meal
from app.llm import estimate_with_llm
from app.schema import NutritionEstimate

log = logging.getLogger(__name__)

MAX_INPUT_CHARS = 500  # longer text is almost certainly not one meal, and costs LLM tokens

# (label for logs, function). Each takes the meal text and returns an estimate or None.
STAGES = [
    ("local table", estimate_from_table),
    ("nutrition APIs", estimate_from_apis),
    ("LLM", estimate_with_llm),
]

# Placeholder assumptions: an average food item, split 15% protein / 50% carbs / 35% fat.
PLACEHOLDER_KCAL_PER_ITEM = 250


def placeholder_estimate(meal: str) -> NutritionEstimate:
    """Stage 4: a deliberately rough guess, clearly labelled as such."""
    items = max(len(parse_meal(meal)), 1)
    kcal = PLACEHOLDER_KCAL_PER_ITEM * items
    return NutritionEstimate(
        name=meal,
        calories=kcal,
        protein=kcal * 0.15 / 4,  # 4 kcal per gram of protein
        carbs=kcal * 0.50 / 4,    # 4 kcal per gram of carbs
        fat=kcal * 0.35 / 9,      # 9 kcal per gram of fat
        note=(
            f"ROUGH PLACEHOLDER: no data source could estimate this meal, so "
            f"{items} item(s) x {PLACEHOLDER_KCAL_PER_ITEM} kcal was assumed. "
            "Check your internet connection / API keys, or edit before relying on it."
        ),
        source="fallback",
    )


def estimate_meal(meal: str) -> NutritionEstimate:
    """Run the pipeline. Raises ValueError only for bad *input*; never for failing services."""
    meal = " ".join((meal or "").split())  # trim and collapse whitespace/newlines
    if not meal:
        raise ValueError("Please describe a meal, e.g. '2 rotis and a bowl of dal'.")
    if len(meal) > MAX_INPUT_CHARS:
        raise ValueError(f"Please keep the description under {MAX_INPUT_CHARS} characters.")

    for label, stage in STAGES:
        started = time.perf_counter()
        try:
            result = stage(meal)
        except Exception:  # a bug inside one stage must not take down the whole app
            log.exception("%s stage crashed; moving on", label)  # .exception also logs the traceback
            result = None
        took = time.perf_counter() - started
        if result is not None:
            log.info("%r resolved by %s in %.2fs", meal, label, took)
            return result
        log.info("%s could not resolve %r (%.2fs)", label, meal, took)

    log.warning("All stages failed for %r; using placeholder", meal)
    return placeholder_estimate(meal)
