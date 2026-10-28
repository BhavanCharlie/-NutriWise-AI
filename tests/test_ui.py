"""Test the Gradio handlers as plain functions: no browser needed."""

import gradio as gr

from app import storage, ui

SKIP = gr.skip()


def test_page_load_with_empty_log():
    summary, rows = ui.refresh()
    assert "no meals logged yet" in summary and rows == []


def test_estimate_returns_json_and_state():
    data, state = ui.handle_estimate("2 rotis and a bowl of dal")
    assert data["calories"] == 420
    assert state == {"input": "2 rotis and a bowl of dal", "estimate": data}


def test_estimate_empty_input_changes_nothing():
    assert ui.handle_estimate("   ") == (SKIP, SKIP)


def test_save_reuses_the_last_estimate(monkeypatch):
    _, state = ui.handle_estimate("2 rotis and a bowl of dal")

    def must_not_run(text):
        raise AssertionError("Save re-ran the estimator")

    monkeypatch.setattr(ui, "estimate_meal", must_not_run)
    data, new_state, box, summary, rows = ui.handle_save("2 rotis and a bowl of dal", state)
    assert new_state is None and box == ""
    assert "420 kcal" in summary and len(rows) == 1


def test_save_without_estimating_first():
    *_, rows = ui.handle_save("3 idlis and sambar", None)
    assert rows[0][2] == "3 piece idli, 1 bowl sambar"


def test_delete_with_short_id():
    rec = storage.save_meal(ui.estimate_meal("2 rotis and dal"), "2 rotis and dal")
    box, summary, rows = ui.handle_delete(rec["id"][: ui.SHORT_ID])
    assert box == "" and rows == [] and storage.load_meals() == []


def test_delete_rejects_too_short_or_unknown_ids():
    storage.save_meal(ui.estimate_meal("2 rotis and dal"))
    assert ui.handle_delete("ab") == (SKIP, SKIP, SKIP)
    assert ui.handle_delete("zzzzzzzz") == (SKIP, SKIP, SKIP)
    assert len(storage.load_meals()) == 1


def test_ui_builds():
    assert isinstance(ui.build_ui(), gr.Blocks)
