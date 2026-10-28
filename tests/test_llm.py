import pytest

from app import llm

GOOD = {"name": "Stew", "calories": "320 kcal", "protein": 18, "carbs": 30, "fat": 14, "note": "Assumed 1 bowl."}


class FakeAPIError(Exception):
    """Looks like google.genai's errors: has a numeric .code"""

    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def fake(name, behaviour):
    """Build a provider function that answers `behaviour` and counts its calls."""

    def ask(meal):
        ask.calls += 1
        result = behaviour(ask.calls) if callable(behaviour) else behaviour
        if isinstance(result, Exception):
            raise result
        return result

    ask.calls, ask.__name__ = 0, name
    return ask


def use_providers(monkeypatch, *asks):
    keys = ["GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"]
    sources = ["gemini", "groq", "openrouter"]
    monkeypatch.setattr(llm, "PROVIDERS", list(zip(sources, keys, asks)))


def test_extract_json_from_chatty_reply():
    assert llm._extract_json('Sure! ```json\n{"calories": 100}\n``` hope that helps') == {"calories": 100}
    with pytest.raises(ValueError):
        llm._extract_json("I can't help with that")


def test_first_working_provider_wins(monkeypatch, llm_keys):
    use_providers(monkeypatch, fake("g", GOOD), fake("q", GOOD), fake("o", GOOD))
    e = llm.estimate_with_llm("stew")
    assert (e.source, e.calories) == ("gemini", 320.0)


def test_falls_back_past_bad_key_and_bad_json(monkeypatch, llm_keys):
    bad_key = fake("g", FakeAPIError(401))
    garbage = fake("q", {**GOOD, "calories": "lots"})
    use_providers(monkeypatch, bad_key, garbage, fake("o", GOOD))
    assert llm.estimate_with_llm("stew").source == "openrouter"


def test_transient_error_is_retried(monkeypatch, llm_keys):
    flaky = fake("g", lambda call: FakeAPIError(503) if call == 1 else GOOD)
    use_providers(monkeypatch, flaky, fake("q", GOOD), fake("o", GOOD))
    assert llm.estimate_with_llm("stew").source == "gemini"
    assert flaky.calls == 2


def test_permanent_error_is_not_retried(monkeypatch, llm_keys):
    missing_model = fake("g", FakeAPIError(404))
    use_providers(monkeypatch, missing_model, fake("q", GOOD), fake("o", GOOD))
    assert llm.estimate_with_llm("stew").source == "groq"
    assert missing_model.calls == 1


def test_providers_without_keys_are_skipped(monkeypatch, llm_keys):
    monkeypatch.delenv("GEMINI_API_KEY")
    gemini = fake("g", GOOD)
    use_providers(monkeypatch, gemini, fake("q", GOOD), fake("o", GOOD))
    assert llm.estimate_with_llm("stew").source == "groq"
    assert gemini.calls == 0


def test_all_failing_returns_none(monkeypatch, llm_keys):
    use_providers(monkeypatch, fake("g", FakeAPIError(500)), fake("q", FakeAPIError(429)), fake("o", ValueError("x")))
    assert llm.estimate_with_llm("stew") is None


def test_not_food_is_a_valid_zero(monkeypatch, llm_keys):
    zero = {**GOOD, "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "note": "Not food."}
    use_providers(monkeypatch, fake("g", zero), fake("q", GOOD), fake("o", GOOD))
    assert llm.estimate_with_llm("laptop charger").calories == 0
