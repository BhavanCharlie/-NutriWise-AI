"""Stage 2 of the pipeline: free nutrition APIs.

For each food the parser finds, try these providers in order:
    1. API Ninjas         (only if API_NINJAS_KEY is set; understands "2 cups rice")
    2. USDA FoodData Central (USDA_API_KEY, or the public DEMO_KEY)
    3. Open Food Facts    (no key needed; best for packaged foods)

Every network call is wrapped so a timeout, bad key, 503 or odd JSON
just means "this provider couldn't help", never a crash.
"""

import logging
import os

import requests
from dotenv import load_dotenv

from app.food_table import item_from_table, parse_meal
from app.schema import FoodItem, NutritionEstimate

load_dotenv()  # reads nutriwise/.env into os.environ (safe to call more than once)
log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8
HEADERS = {"User-Agent": "NutriWise-AI/0.1 (learning project)"}  # Open Food Facts asks for this
FIELDS = ("calories", "protein", "carbs", "fat")

# APIs report nutrition per 100 g, so we need a rough weight for each unit.
GRAMS_PER_UNIT = {
    "g": 1, "piece": 100, "bowl": 150, "plate": 250, "cup": 240, "glass": 250,
    # Bread slices (~30 g) come from the local table, so "slice" here means pizza, cake, etc.
    "slice": 100, "tbsp": 15, "tsp": 5, "serving": 100,
}


def _get_json(url: str, params: dict, headers: dict | None = None):
    """GET a URL and return parsed JSON, or None on ANY network/HTTP/JSON problem."""
    try:
        response = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()  # turns 4xx/5xx status codes into exceptions
        return response.json()
    except requests.RequestException as err:  # timeout, DNS, 503, bad JSON, ...
        # Log only the base URL and status: the full error text contains the
        # query string, which would leak api_key into logs and screenshots.
        status = getattr(err.response, "status_code", None)
        log.warning("Request to %s failed: %s (status %s)", url, type(err).__name__, status)
        return None


def _looks_valid(per_100g: dict) -> bool:
    """Reject impossible numbers. Pure fat is ~900 kcal/100 g, so more than that is junk."""
    return all(isinstance(per_100g[f], (int, float)) for f in FIELDS) and 0 < per_100g["calories"] <= 900


# ---------------------------------------------------------------------------
# Relevance: search engines always return *something*; make sure it's the food we asked for
# ---------------------------------------------------------------------------
# Processed forms that are rarely what someone means by "banana" or "milk".
UNLIKELY_WORDS = {"dehydrated", "powder", "dry", "dried", "mix", "babyfood", "juice", "chips", "concentrate"}


def _words(text: str) -> set[str]:
    """'Bananas, raw' -> {'banana', 'raw'}  (lowercase, letters only, crude singular)"""
    tokens = "".join(c if c.isalpha() else " " for c in text.lower()).split()
    return {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in tokens}


def relevance(query: str, description: str, main_part_only: bool = False) -> float | None:
    """Score how well a search result matches the query. Lower is better; None = reject.

    Every query word must appear in the description. With main_part_only, one of
    them must also be in the text before the first comma: USDA puts the main food
    there ("Bread, oatmeal" is bread, not oatmeal).
    """
    wanted, found = _words(query), _words(description)
    if not wanted or not wanted <= found:  # <= on sets means "is a subset of"
        return None
    if main_part_only and not wanted & _words(description.split(",")[0]):
        return None
    extra = found - wanted
    return len(extra) + 5 * len((extra & UNLIKELY_WORDS))


def best_match(query: str, results: list[dict], key: str, main_part_only: bool = False) -> dict | None:
    """Pick the most relevant result (a dict) by its `key` text, or None if none qualify."""
    scored = [(relevance(query, r.get(key) or "", main_part_only), r) for r in results]
    scored = [(score, r) for score, r in scored if score is not None]
    if not scored:
        return None
    return min(scored, key=lambda pair: pair[0])[1]


# ---------------------------------------------------------------------------
# Providers: each returns (label, totals_dict) for ONE item, or None
# ---------------------------------------------------------------------------
def from_api_ninjas(item: FoodItem) -> tuple[str, dict] | None:
    key = os.getenv("API_NINJAS_KEY")
    if not key:
        return None
    unit = "" if item.unit == "serving" else f" {item.unit}"
    data = _get_json(
        "https://api.api-ninjas.com/v1/nutrition",
        params={"query": f"{item.quantity:g}{unit} {item.name}"},
        headers={"X-Api-Key": key},
    )
    if not data:  # None (failed) or [] (food not recognised)
        return None
    totals = {
        "calories": sum(_num(d.get("calories")) for d in data),
        "protein": sum(_num(d.get("protein_g")) for d in data),
        "carbs": sum(_num(d.get("carbohydrates_total_g")) for d in data),
        "fat": sum(_num(d.get("fat_total_g")) for d in data),
    }
    # The free tier hides calories ("Only available for premium subscribers").
    if totals["calories"] <= 0:
        log.info("API Ninjas returned no calories for %r (free tier?)", item.name)
        return None
    return "API Ninjas", totals


def _num(value) -> float:
    return value if isinstance(value, (int, float)) else 0.0


def usda_per_100g(name: str) -> tuple[str, dict] | None:
    data = _get_json(
        "https://api.nal.usda.gov/fdc/v1/foods/search",
        params={
            "query": name,
            "pageSize": 10,
            "dataType": "Foundation,SR Legacy",  # generic foods, not branded products
            "api_key": os.getenv("USDA_API_KEY") or "DEMO_KEY",
        },
    )
    if not data:
        return None
    food = best_match(name, data.get("foods", []), key="description", main_part_only=True)
    if food is None:
        return None
    per_100g = {f: None for f in FIELDS}
    for n in food.get("foodNutrients", []):
        nutrient, unit = n.get("nutrientName", ""), n.get("unitName", "").upper()
        if nutrient.startswith("Energy") and unit == "KCAL":
            per_100g["calories"] = n.get("value")
        elif nutrient == "Protein":
            per_100g["protein"] = n.get("value")
        elif nutrient == "Carbohydrate, by difference":
            per_100g["carbs"] = n.get("value")
        elif nutrient == "Total lipid (fat)":
            per_100g["fat"] = n.get("value")
    if not _looks_valid(per_100g):
        return None
    return f"USDA: {food['description'].title()}", per_100g


def open_food_facts_per_100g(name: str) -> tuple[str, dict] | None:
    data = _get_json(
        "https://search.openfoodfacts.org/search",
        params={"q": name, "page_size": 5, "fields": "product_name,nutriments"},
    )
    if not data:
        return None
    product = best_match(name, data.get("hits", []), key="product_name")
    if product is None:
        return None
    n = product.get("nutriments", {})
    per_100g = {
        "calories": n.get("energy-kcal_100g"),
        "protein": n.get("proteins_100g"),
        "carbs": n.get("carbohydrates_100g"),
        "fat": n.get("fat_100g"),
    }
    if not _looks_valid(per_100g):
        return None
    return f"Open Food Facts: {product.get('product_name', name)}", per_100g


def _scale(per_100g: dict, item: FoodItem) -> tuple[dict, float]:
    """Convert per-100 g values into totals for this item's portion."""
    grams = item.quantity * GRAMS_PER_UNIT.get(item.unit, 100)
    return {f: per_100g[f] * grams / 100 for f in FIELDS}, grams


def lookup_item(item: FoodItem) -> tuple[str, dict] | None:
    """Try each provider for one food. Returns (description, totals) or None."""
    found = from_api_ninjas(item)
    if found:
        return found
    for provider in (usda_per_100g, open_food_facts_per_100g):
        found = provider(item.name)
        if found:
            label, per_100g = found
            totals, grams = _scale(per_100g, item)
            return f"{label} (~{grams:g} g)", totals
    return None


def estimate_from_apis(text: str) -> NutritionEstimate | None:
    """Stage 2: estimate a meal from nutrition APIs, or None if any food can't be found."""
    items = parse_meal(text)
    if not items:
        return None

    totals = dict.fromkeys(FIELDS, 0.0)
    matches = []
    for item in items:
        # Foods the local table knows ("2 roti and pizza") don't need a web search.
        known = item_from_table(item)
        if known:
            label, item_totals, _ = known
            for f in FIELDS:
                totals[f] += item_totals[f]
            matches.append(f"{label} -> local table")
            continue
        found = lookup_item(item)
        if found is None:
            log.info("No API could resolve %r", item.name)
            return None  # all-or-nothing, same rule as Stage 1
        label, item_totals = found
        for f in FIELDS:
            totals[f] += item_totals[f]
        matches.append(f"{item.name} -> {label}")

    note = "Nutrition API matches: " + "; ".join(matches) + ". Portion weights are estimated."
    return NutritionEstimate(name=text.strip(), note=note, source="nutrition_api", **totals)
