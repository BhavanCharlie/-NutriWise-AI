"""Stage 1 of the pipeline: a local food table plus a free-text meal parser.

parse_meal("2 rotis and a bowl of dal")
    -> [FoodItem(name='roti', quantity=2, unit='serving'),
        FoodItem(name='dal',  quantity=1, unit='bowl')]

estimate_from_table(text) returns a NutritionEstimate if EVERY food is in the
table, otherwise None so the pipeline can try the next stage.
"""

import re

from app.schema import FoodItem, NutritionEstimate

# ---------------------------------------------------------------------------
# 1. The food table
# ---------------------------------------------------------------------------
# Values are approximate, for ONE typical home-cooked serving.
# "unit" is what one serving means; "grams" is its rough weight, used when
# the user gives a weight like "200g rice".
FOOD_TABLE: dict[str, dict] = {
    # Breads
    "roti":            {"unit": "piece", "grams": 40,  "calories": 120, "protein": 3,   "carbs": 18,  "fat": 3.5},
    "paratha":         {"unit": "piece", "grams": 60,  "calories": 200, "protein": 4,   "carbs": 28,  "fat": 8},
    "aloo paratha":    {"unit": "piece", "grams": 100, "calories": 290, "protein": 6,   "carbs": 40,  "fat": 12},
    "bread":           {"unit": "slice", "grams": 30,  "calories": 80,  "protein": 3,   "carbs": 14,  "fat": 1},
    # Rice dishes
    "rice":            {"unit": "bowl",  "grams": 150, "calories": 195, "protein": 4,   "carbs": 42,  "fat": 0.5},
    "fried rice":      {"unit": "plate", "grams": 200, "calories": 330, "protein": 7,   "carbs": 50,  "fat": 11},
    "chicken biryani": {"unit": "plate", "grams": 250, "calories": 450, "protein": 22,  "carbs": 55,  "fat": 15},
    "khichdi":         {"unit": "bowl",  "grams": 200, "calories": 250, "protein": 9,   "carbs": 40,  "fat": 6},
    # Curries and dals
    "dal":             {"unit": "bowl",  "grams": 150, "calories": 180, "protein": 9,   "carbs": 24,  "fat": 5},
    "rajma":           {"unit": "bowl",  "grams": 150, "calories": 210, "protein": 10,  "carbs": 30,  "fat": 5},
    "chole":           {"unit": "bowl",  "grams": 150, "calories": 250, "protein": 10,  "carbs": 32,  "fat": 9},
    "sambar":          {"unit": "bowl",  "grams": 150, "calories": 130, "protein": 6,   "carbs": 18,  "fat": 4},
    "paneer butter masala": {"unit": "bowl", "grams": 150, "calories": 330, "protein": 12, "carbs": 12, "fat": 26},
    "chicken curry":   {"unit": "bowl",  "grams": 150, "calories": 240, "protein": 20,  "carbs": 6,   "fat": 15},
    # Breakfast
    "idli":            {"unit": "piece", "grams": 40,  "calories": 58,  "protein": 2,   "carbs": 12,  "fat": 0.4},
    "dosa":            {"unit": "piece", "grams": 80,  "calories": 170, "protein": 4,   "carbs": 28,  "fat": 4},
    "poha":            {"unit": "plate", "grams": 150, "calories": 250, "protein": 5,   "carbs": 45,  "fat": 6},
    "upma":            {"unit": "bowl",  "grams": 150, "calories": 230, "protein": 6,   "carbs": 35,  "fat": 8},
    "oats":            {"unit": "bowl",  "grams": 200, "calories": 150, "protein": 5,   "carbs": 27,  "fat": 3},
    "egg":             {"unit": "piece", "grams": 50,  "calories": 78,  "protein": 6.3, "carbs": 0.6, "fat": 5.3},
    "omelette":        {"unit": "piece", "grams": 120, "calories": 190, "protein": 13,  "carbs": 2,   "fat": 14},
    # Dairy and drinks
    "curd":            {"unit": "bowl",  "grams": 150, "calories": 90,  "protein": 5,   "carbs": 7,   "fat": 5},
    "milk":            {"unit": "glass", "grams": 250, "calories": 150, "protein": 8,   "carbs": 12,  "fat": 8},
    "butter":          {"unit": "tbsp",  "grams": 14,  "calories": 100, "protein": 0.1, "carbs": 0,   "fat": 11.5},
    "peanut butter":   {"unit": "tbsp",  "grams": 16,  "calories": 95,  "protein": 3.5, "carbs": 3.5, "fat": 8},
    "tea":             {"unit": "cup",   "grams": 150, "calories": 70,  "protein": 2,   "carbs": 10,  "fat": 2},
    "coffee":          {"unit": "cup",   "grams": 150, "calories": 60,  "protein": 2,   "carbs": 8,   "fat": 2},
    # Fruit, snacks, sides
    "banana":          {"unit": "piece", "grams": 118, "calories": 105, "protein": 1.3, "carbs": 27,  "fat": 0.4},
    "apple":           {"unit": "piece", "grams": 180, "calories": 95,  "protein": 0.5, "carbs": 25,  "fat": 0.3},
    "samosa":          {"unit": "piece", "grams": 80,  "calories": 260, "protein": 4,   "carbs": 30,  "fat": 14},
    "salad":           {"unit": "bowl",  "grams": 100, "calories": 30,  "protein": 1,   "carbs": 6,   "fat": 0.2},
}

# Other names people use for the same food -> the key in FOOD_TABLE.
ALIASES: dict[str, str] = {
    "chapati": "roti", "chapatti": "roti", "phulka": "roti",
    "dahi": "curd", "yogurt": "curd", "yoghurt": "curd",
    "chai": "tea",
    "chana masala": "chole", "chickpea curry": "chole",
    "biryani": "chicken biryani",
    "eggs": "egg", "omelet": "omelette",
    "oatmeal": "oats", "porridge": "oats",
}

# ---------------------------------------------------------------------------
# 2. Words the parser understands
# ---------------------------------------------------------------------------
NUMBER_WORDS: dict[str, float] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5,
}

# Every unit spelling -> one canonical unit name.
UNITS: dict[str, str] = {
    "piece": "piece", "pc": "piece",
    "bowl": "bowl", "katori": "bowl",
    "plate": "plate", "cup": "cup", "glass": "glass", "slice": "slice",
    "tablespoon": "tbsp", "tbsp": "tbsp", "teaspoon": "tsp", "tsp": "tsp",
    "serving": "serving",
    "gram": "g", "gm": "g", "g": "g",
}

# Describing words that confuse lookups ("extra butter" -> "Extra Butter Popcorn").
FILLER_WORDS = re.compile(r"\b(extra|some|little|bit of|plain|fresh|homemade|home made)\b")

# Splits "2 roti, dal and rice with curd" into separate foods.
SEPARATORS = re.compile(r",|;|\+|&|\band\b|\bwith\b")

# Sort longest first so "tablespoon" is tried before "tbsp" and "gram" before "g".
_unit_pattern = "|".join(sorted(UNITS, key=len, reverse=True))
_number_pattern = "|".join(NUMBER_WORDS)

# One food chunk:  [quantity] [unit] [of] name
ITEM_PATTERN = re.compile(
    rf"""^
    (?P<qty>\d+/\d+ | \d+(?:\.\d+)? | (?:{_number_pattern})\b)?   # 2, 1.5, 1/2, two, a
    \s*(?:an?\s+)?                                               # the 'a' in 'half a bowl'
    (?:(?P<unit>{_unit_pattern})(?:e?s)?\b)?                     # bowl, bowls, glasses, g
    \s*(?:of\s+)?                                                # optional 'of'
    (?P<name>.+?)                                                # whatever is left
    $""",
    re.VERBOSE,
)


def _to_quantity(text: str | None) -> float:
    """'2' -> 2.0, '1/2' -> 0.5, 'two' -> 2.0, None -> 1.0"""
    if not text:
        return 1.0
    if "/" in text:
        top, bottom = text.split("/")
        return float(top) / float(bottom)
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    return float(text)


def parse_meal(text: str) -> list[FoodItem]:
    """Turn free text into a list of FoodItem objects."""
    items = []
    for chunk in SEPARATORS.split(text.lower()):
        chunk = chunk.strip(" .!")
        if not chunk:
            continue
        match = ITEM_PATTERN.match(chunk)
        if not match:  # can't happen with this pattern, but be defensive
            continue
        unit = UNITS.get(match["unit"] or "", "serving")
        name = " ".join(FILLER_WORDS.sub(" ", match["name"]).split()) or match["name"].strip()
        items.append(FoodItem(name=name, quantity=_to_quantity(match["qty"]), unit=unit))
    return items


# ---------------------------------------------------------------------------
# 3. Looking foods up
# ---------------------------------------------------------------------------
def _singular_forms(name: str) -> list[str]:
    """'rotis' -> ['rotis', 'roti'];  'tomatoes' -> ['tomatoes', 'tomatoe', 'tomato']"""
    forms = [name]
    if name.endswith("s"):
        forms.append(name[:-1])
    if name.endswith("es"):
        forms.append(name[:-2])
    return forms


def lookup_food(name: str) -> tuple[str, dict] | None:
    """Find the best FOOD_TABLE entry for a food name, or None.

    Tries exact name, aliases, then singular forms. If none match exactly,
    looks for a table key inside the name as a whole word ("masala dosa"
    -> "dosa"), preferring the longest key ("fried rice" beats "rice").
    """
    for form in _singular_forms(name):
        key = ALIASES.get(form, form)
        if key in FOOD_TABLE:
            return key, FOOD_TABLE[key]

    candidates = list(FOOD_TABLE) + list(ALIASES)
    for key in sorted(candidates, key=len, reverse=True):
        for form in _singular_forms(name):
            if re.search(rf"\b{re.escape(key)}\b", form):
                key = ALIASES.get(key, key)
                return key, FOOD_TABLE[key]
    return None


def _servings(item: FoodItem, entry: dict) -> tuple[float, str | None]:
    """How many table servings this item is, plus an assumption note if any."""
    if item.unit == "g":
        return item.quantity / entry["grams"], None
    if item.unit in ("serving", entry["unit"]):
        return item.quantity, None
    return item.quantity, f"treated 1 {item.unit} as 1 {entry['unit']}"


def _fmt(qty: float) -> str:
    """2.0 -> '2', 0.5 -> '0.5'"""
    return f"{qty:g}"


def item_from_table(item: FoodItem) -> tuple[str, dict, list[str]] | None:
    """Look up ONE parsed item. Returns (label, totals, assumption notes) or None.

    Shared by Stage 1 and by Stage 2, which uses it for the foods we already know.
    """
    found = lookup_food(item.name)
    if found is None:
        return None
    key, entry = found
    servings, note = _servings(item, entry)
    totals = {field: entry[field] * servings for field in ("calories", "protein", "carbs", "fat")}
    unit = entry["unit"] if item.unit == "serving" else item.unit
    notes = [f"{key}: {note}"] if note else []
    # Be honest when "masala dosa" was only matched to plain "dosa".
    if key not in [ALIASES.get(form, form) for form in _singular_forms(item.name)]:
        notes.append(f"'{item.name}' approximated as '{key}'")
    return f"{_fmt(item.quantity)} {unit} {key}", totals, notes


def estimate_from_table(text: str) -> NutritionEstimate | None:
    """Stage 1: estimate a meal from the local table, or None if any food is unknown."""
    items = parse_meal(text)
    if not items:
        return None

    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    labels, notes = [], []
    for item in items:
        found = item_from_table(item)
        if found is None:
            return None  # all-or-nothing: let a smarter stage handle the whole meal
        label, item_totals, item_notes = found
        for field in totals:
            totals[field] += item_totals[field]
        labels.append(label)
        notes += item_notes

    note = "Typical home-cooked portions from the local table."
    if notes:
        note += " Assumptions: " + "; ".join(notes) + "."
    return NutritionEstimate(name=", ".join(labels), note=note, source="local_table", **totals)
