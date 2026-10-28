"""Data shapes used everywhere in NutriWise.

Every stage of the pipeline (local table, nutrition API, LLM, fallback)
must return a NutritionEstimate, so the UI and storage never have to care
where a number came from.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# The only allowed values for `source`. Anything else is a validation error.
Source = Literal["local_table", "nutrition_api", "gemini", "groq", "openrouter", "fallback"]


class FoodItem(BaseModel):
    """One food the parser found in the meal text, e.g. '2 roti'."""

    name: str = Field(min_length=1)
    quantity: float = Field(default=1, gt=0)
    unit: str = "serving"


class NutritionEstimate(BaseModel):
    """The normalized result for a whole meal."""

    name: str = Field(min_length=1, description="Short meal name")
    calories: float = Field(ge=0, description="kcal")
    protein: float = Field(default=0, ge=0, description="grams")
    carbs: float = Field(default=0, ge=0, description="grams")
    fat: float = Field(default=0, ge=0, description="grams")
    note: str = Field(default="", description="Assumptions / uncertainty")
    source: Source

    @field_validator("calories", "protein", "carbs", "fat", mode="before")
    @classmethod
    def to_number(cls, value):
        """Accept messy input like '250 kcal', '12.5g' or None.

        Runs *before* Pydantic's own type check, so we can clean the value first.
        LLMs and APIs often return numbers as strings with units attached.
        """
        if value is None:
            return 0
        if isinstance(value, str):
            match = re.search(r"-?\d+(\.\d+)?", value)
            if not match:
                raise ValueError(f"no number found in {value!r}")
            return float(match.group())
        return value

    @field_validator("calories", "protein", "carbs", "fat")
    @classmethod
    def round_one_decimal(cls, value: float) -> float:
        """Runs *after* the type check, so value is guaranteed to be a float."""
        return round(value, 1)
