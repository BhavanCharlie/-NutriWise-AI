"""Meal log stored in a plain JSON file (no database needed).

data/meals.json holds a list of records, newest first:
    [{"id": "3f2a...", "date": "2026-10-28", "created_at": "2026-10-28T13:05:12+05:30",
      "input": "2 rotis and dal", "name": "...", "calories": 420.0, ..., "source": "local_table"}]

Every function takes an optional `path`, so tests can use a temporary file
instead of your real log.
"""

import json
import logging
import os
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from app.schema import NutritionEstimate

log = logging.getLogger(__name__)

# Built from this file's location, so it works no matter which folder you run from.
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "meals.json"

# Gradio can run two button clicks at the same time; the lock makes each
# read-modify-write finish before the next one starts.
_lock = threading.Lock()


def _resolve(path: Path | None) -> Path:
    """None -> DATA_FILE, looked up at CALL time.

    A default like `path=DATA_FILE` would be frozen when the function is defined,
    so tests (or a config change) couldn't point the module at another file.
    """
    return Path(path) if path is not None else DATA_FILE


def load_meals(path: Path | None = None) -> list[dict]:
    """Return all saved meals (newest first). Missing file -> []. Corrupt file -> backed up, then []."""
    path = _resolve(path)
    if not path.exists():
        return []
    try:
        meals = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(meals, list):
            raise ValueError("top level is not a list")
        return meals
    except (json.JSONDecodeError, ValueError) as err:
        # Never silently throw away someone's history: keep the broken file for inspection.
        backup = path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json")
        path.rename(backup)
        log.error("%s was unreadable (%s); moved it to %s and started a fresh log", path.name, err, backup.name)
        return []


def _write_meals(meals: list[dict], path: Path) -> None:
    """Atomic write: write a temp file, then swap it in with one rename.

    If the app crashes halfway through writing, the old file is still intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meals, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic on macOS, Linux and Windows


def save_meal(estimate: NutritionEstimate, meal_text: str = "", path: Path | None = None) -> dict:
    """Add an estimate to the top of the log and return the saved record."""
    now = datetime.now().astimezone()  # local time WITH its UTC offset, e.g. +05:30
    record = {
        "id": uuid.uuid4().hex,
        "date": now.date().isoformat(),  # "2026-10-28": used to group meals by day
        "created_at": now.isoformat(timespec="seconds"),
        "input": meal_text,
        **estimate.model_dump(),
    }
    with _lock:
        meals = load_meals(path)
        meals.insert(0, record)  # newest first
        _write_meals(meals, _resolve(path))
    return record


def delete_meal(meal_id: str, path: Path | None = None) -> bool:
    """Remove a meal by id. Returns True if something was deleted."""
    meal_id = (meal_id or "").strip()
    with _lock:
        meals = load_meals(path)
        kept = [m for m in meals if m.get("id") != meal_id]
        if len(kept) == len(meals):
            return False
        _write_meals(kept, _resolve(path))
    return True


def meals_for_day(day: date | None = None, path: Path | None = None) -> list[dict]:
    """All meals saved on `day` (default: today, in local time)."""
    day_str = (day or date.today()).isoformat()
    return [m for m in load_meals(path) if m.get("date") == day_str]


def daily_totals(day: date | None = None, path: Path | None = None) -> dict:
    """Sum calories and macros for one day."""
    meals = meals_for_day(day, path)
    totals = {f: round(sum(m.get(f, 0) for m in meals), 1) for f in ("calories", "protein", "carbs", "fat")}
    return {"meals": len(meals), **totals}
