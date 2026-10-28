import pytest
from pydantic import ValidationError

from app.schema import FoodItem, NutritionEstimate


def test_messy_numbers_are_cleaned():
    e = NutritionEstimate(name="Paneer", calories="265 kcal", protein="18.33g", carbs=None, fat=20, source="gemini")
    assert (e.calories, e.protein, e.carbs, e.fat) == (265.0, 18.3, 0.0, 20.0)


def test_optional_fields_have_defaults():
    e = NutritionEstimate(name="Idli", calories=58, source="local_table")
    assert e.protein == 0 and e.note == ""


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "", "calories": 100, "source": "gemini"},         # empty name
        {"name": "x", "calories": -5, "source": "gemini"},         # negative calories
        {"name": "x", "calories": 100, "source": "chatgpt"},       # unknown source
        {"name": "x", "calories": "lots", "source": "gemini"},     # no number in text
        {"name": "x", "source": "gemini"},                         # calories missing
    ],
)
def test_invalid_estimates_are_rejected(bad):
    with pytest.raises(ValidationError):
        NutritionEstimate(**bad)


def test_food_item_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        FoodItem(name="roti", quantity=0)
