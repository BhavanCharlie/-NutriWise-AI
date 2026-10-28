import pytest

from app import estimator
from app.schema import NutritionEstimate


def none(meal):
    return None


def crash(meal):
    raise ZeroDivisionError("simulated bug")


def llm_answer(meal):
    return NutritionEstimate(name=meal, calories=400, source="gemini")


def test_local_table_answers_first():
    assert estimator.estimate_meal("2 rotis and a bowl of dal").source == "local_table"


def test_falls_through_to_later_stages(monkeypatch):
    monkeypatch.setattr(estimator, "STAGES", [("table", none), ("apis", none), ("llm", llm_answer)])
    assert estimator.estimate_meal("mystery stew").source == "gemini"


def test_crashing_stage_is_skipped(monkeypatch):
    monkeypatch.setattr(estimator, "STAGES", [("table", none), ("apis", crash), ("llm", llm_answer)])
    assert estimator.estimate_meal("mystery stew").source == "gemini"


def test_everything_failing_gives_labelled_placeholder(monkeypatch):
    monkeypatch.setattr(estimator, "STAGES", [("table", none), ("apis", crash), ("llm", none)])
    e = estimator.estimate_meal("pizza and coke")
    assert e.source == "fallback"
    assert e.calories == 2 * estimator.PLACEHOLDER_KCAL_PER_ITEM
    assert "ROUGH PLACEHOLDER" in e.note


def test_works_offline_with_the_real_pipeline():
    # conftest blocks all network calls: the table still works, the rest falls back
    assert estimator.estimate_meal("2 rotis and dal").source == "local_table"
    assert estimator.estimate_meal("pizza and coke").source == "fallback"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 501])
def test_bad_input_raises_value_error(bad):
    with pytest.raises(ValueError):
        estimator.estimate_meal(bad)
