"""Smoke tests against the REAL services. Skipped by default (see pytest.ini).

Run them on purpose, e.g. before a demo:   pytest -m live
They need internet and use a little API quota.
"""

import os

import pytest

from app.apis import usda_per_100g
from app.llm import estimate_with_llm

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_llm_chain_estimates_a_real_meal():
    e = estimate_with_llm("1 plate pav bhaji")
    assert e is not None, "every configured LLM failed - check keys/quota in the logs"
    assert 200 < e.calories < 1500
    # macros should roughly agree with calories (4/4/9 rule)
    assert abs(4 * e.protein + 4 * e.carbs + 9 * e.fat - e.calories) < 0.25 * e.calories


def test_usda_finds_banana():
    label, per_100g = usda_per_100g("banana")
    assert "Banana" in label and 70 < per_100g["calories"] < 120
