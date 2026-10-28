import threading
from datetime import date, timedelta

import pytest

from app import storage
from app.schema import NutritionEstimate


def make(calories=100, name="Test"):
    return NutritionEstimate(name=name, calories=calories, protein=5, carbs=10, fat=2, source="local_table")


def test_missing_file_means_empty_log():
    assert storage.load_meals() == []
    assert storage.daily_totals() == {"meals": 0, "calories": 0, "protein": 0, "carbs": 0, "fat": 0}


def test_saved_record_has_required_fields():
    rec = storage.save_meal(make(), "2 rotis")
    assert len(rec["id"]) == 32
    assert rec["date"] == date.today().isoformat()
    assert rec["created_at"].startswith(rec["date"])
    assert rec["input"] == "2 rotis" and rec["calories"] == 100 and rec["source"] == "local_table"


def test_newest_meal_is_first():
    storage.save_meal(make(name="first"))
    storage.save_meal(make(name="second"))
    assert [m["name"] for m in storage.load_meals()] == ["second", "first"]


def test_daily_totals_only_count_that_day():
    storage.save_meal(make(100))
    old = storage.save_meal(make(250))
    meals = storage.load_meals()
    yesterday = date.today() - timedelta(days=1)
    for m in meals:
        if m["id"] == old["id"]:
            m["date"] = yesterday.isoformat()
    storage._write_meals(meals, storage.DATA_FILE)

    assert storage.daily_totals()["calories"] == 100
    assert storage.daily_totals(yesterday)["calories"] == 250


def test_delete_by_id():
    keep, gone = storage.save_meal(make(name="keep")), storage.save_meal(make(name="gone"))
    assert storage.delete_meal(gone["id"]) is True
    assert storage.delete_meal(gone["id"]) is False  # already deleted
    assert storage.delete_meal("not-an-id") is False
    assert [m["id"] for m in storage.load_meals()] == [keep["id"]]


def test_corrupt_file_is_backed_up_not_lost(temp_data_file):
    temp_data_file.write_text('[{"id": "abc", "calories": 4')  # half-written JSON
    assert storage.load_meals() == []
    backups = list(temp_data_file.parent.glob("meals.corrupt-*.json"))
    assert len(backups) == 1 and "abc" in backups[0].read_text()


def test_concurrent_saves_are_not_lost():
    threads = [threading.Thread(target=lambda: [storage.save_meal(make()) for _ in range(5)]) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(storage.load_meals()) == 50


def test_crash_while_writing_keeps_old_file(monkeypatch, temp_data_file):
    storage.save_meal(make())
    before = temp_data_file.read_text()
    monkeypatch.setattr(storage.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("power cut")))
    with pytest.raises(OSError):
        storage.save_meal(make())
    assert temp_data_file.read_text() == before
