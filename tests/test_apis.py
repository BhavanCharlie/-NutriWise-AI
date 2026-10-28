import logging
from unittest.mock import Mock

import requests

from app import apis

PIZZA_PER_100G = {"calories": 270, "protein": 11, "carbs": 30, "fat": 12}


def test_relevance_prefers_the_plain_food():
    assert apis.relevance("banana", "Bananas, raw") < apis.relevance("banana", "Bananas, dehydrated, or banana powder")


def test_relevance_rejects_wrong_foods():
    assert apis.relevance("oatmeal", "Bread, oatmeal", main_part_only=True) is None  # it's bread
    assert apis.relevance("grandma's mystery stew", "Chicken, stewing, cooked, stewed") is None


def test_best_match_picks_lowest_score():
    results = [{"description": "Bananas, dehydrated, or banana powder"}, {"description": "Bananas, raw"}]
    assert apis.best_match("banana", results, key="description")["description"] == "Bananas, raw"


def test_impossible_values_are_rejected():
    assert not apis._looks_valid({"calories": 5000, "protein": 1, "carbs": 1, "fat": 1})
    assert not apis._looks_valid({"calories": None, "protein": 1, "carbs": 1, "fat": 1})
    assert apis._looks_valid(PIZZA_PER_100G)


def test_per_100g_values_are_scaled_to_the_portion(monkeypatch):
    monkeypatch.setattr(apis, "usda_per_100g", lambda name: ("USDA: Pizza", PIZZA_PER_100G))
    e = apis.estimate_from_apis("2 slices of pizza")  # 2 x 100 g
    assert e.calories == 540 and e.source == "nutrition_api"


def test_known_foods_use_the_local_table(monkeypatch):
    searched = []
    monkeypatch.setattr(apis, "usda_per_100g", lambda name: searched.append(name) or ("USDA: Pizza", PIZZA_PER_100G))
    e = apis.estimate_from_apis("2 roti and a slice of pizza")
    assert searched == ["pizza"]  # roti was NOT searched online
    assert e.calories == 2 * 120 + 270


def test_network_failure_returns_none():
    # conftest blocks the network, so every provider fails
    assert apis.estimate_from_apis("2 slices of pizza") is None


def test_errors_do_not_leak_api_keys(monkeypatch, caplog):
    err = requests.HTTPError("429 Too Many Requests for url: https://x?api_key=SECRET123")
    err.response = Mock(status_code=429)
    monkeypatch.setattr(requests, "get", Mock(side_effect=err))
    with caplog.at_level(logging.WARNING):
        assert apis._get_json("https://x", params={"api_key": "SECRET123"}) is None
    assert "429" in caplog.text
    assert "SECRET123" not in caplog.text
