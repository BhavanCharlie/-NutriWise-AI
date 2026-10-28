"""Gradio web interface. All logic lives in estimator.py / storage.py;
this file only turns button clicks into calls and results into components.

Run it:
    python main.py                      # command line / web app
    from app.ui import launch; launch() # inside a Jupyter notebook
"""

from datetime import date, datetime

import gradio as gr

from app.estimator import estimate_meal
from app.schema import NutritionEstimate
from app.storage import daily_totals, delete_meal, load_meals, meals_for_day, save_meal

HEADERS = ["ID", "Time", "Meal", "kcal", "Protein (g)", "Carbs (g)", "Fat (g)", "Source"]
SHORT_ID = 8  # show only the first 8 of the 32 id characters

SOURCE_LABELS = {
    "local_table": "Local table",
    "nutrition_api": "Nutrition API",
    "gemini": "Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "fallback": "Rough guess",
}

EXAMPLES = [
    "2 rotis and a bowl of dal",
    "3 idlis with sambar and a cup of chai",
    "200g grilled chicken breast and a bowl of rice",
    "1 plate pav bhaji with extra butter",
    "a bowl of grandma's mystery stew",
]


# ---------------------------------------------------------------------------
# Display helpers: turn stored data into what the components show
# ---------------------------------------------------------------------------
def todays_rows() -> list[list]:
    """Today's saved meals as table rows, newest first."""
    rows = []
    for m in meals_for_day():
        time = datetime.fromisoformat(m["created_at"]).strftime("%H:%M")
        rows.append([
            m["id"][:SHORT_ID], time, m["name"], m["calories"],
            m["protein"], m["carbs"], m["fat"], SOURCE_LABELS.get(m["source"], m["source"]),
        ])
    return rows


def summary_line() -> str:
    """One-line daily summary in Markdown."""
    t = daily_totals()
    today = date.today().strftime("%a %d %b")
    if t["meals"] == 0:
        return f"**Today ({today}):** no meals logged yet."
    plural = "meal" if t["meals"] == 1 else "meals"
    return (
        f"**Today ({today}):** {t['meals']} {plural} · **{t['calories']:,.0f} kcal** · "
        f"protein {t['protein']:g} g · carbs {t['carbs']:g} g · fat {t['fat']:g} g"
    )


def refresh():
    """Current summary + table (used on page load and after every change)."""
    return summary_line(), todays_rows()


# ---------------------------------------------------------------------------
# Button handlers: each returns one value per output component, in order
# ---------------------------------------------------------------------------
def handle_estimate(meal_text: str):
    """Estimate button -> (JSON panel, latest-estimate state)."""
    try:
        estimate = estimate_meal(meal_text)
    except ValueError as err:  # empty / too long input
        gr.Warning(str(err))
        return gr.skip(), gr.skip()  # gr.skip() = leave this component unchanged
    data = estimate.model_dump()
    return data, {"input": meal_text.strip(), "estimate": data}


def handle_save(meal_text: str, latest: dict | None):
    """Save button -> (JSON, state, meal box, summary, table).

    Reuses the last estimate if it was for this exact text, so Save doesn't
    call the LLM a second time; otherwise estimates first.
    """
    text = (meal_text or "").strip()
    if latest and latest["input"] == text:
        estimate = NutritionEstimate(**latest["estimate"])
    else:
        try:
            estimate = estimate_meal(text)
        except ValueError as err:
            gr.Warning(str(err))
            return gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip()
    save_meal(estimate, text)
    gr.Info(f"Saved: {estimate.name} ({estimate.calories:g} kcal)")
    return estimate.model_dump(), None, "", *refresh()


def handle_delete(short_id: str):
    """Delete button -> (delete box, summary, table). Accepts the short id shown in the table."""
    short_id = (short_id or "").strip().lower()
    if len(short_id) < 4:
        gr.Warning("Click a row in the table, or type at least 4 characters of its ID.")
        return gr.skip(), gr.skip(), gr.skip()
    matches = [m for m in load_meals() if m["id"].startswith(short_id)]
    if len(matches) != 1:
        gr.Warning("No meal with that ID." if not matches else "That ID matches several meals; type more of it.")
        return gr.skip(), gr.skip(), gr.skip()
    delete_meal(matches[0]["id"])
    gr.Info(f"Deleted: {matches[0]['name']}")
    return "", *refresh()


def handle_row_click(evt: gr.SelectData) -> str:
    """Clicking any cell in a row puts that row's ID into the delete box."""
    return evt.row_value[0]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    # analytics_enabled=False: Gradio otherwise sends usage telemetry to huggingface.co.
    with gr.Blocks(title="NutriWise AI", analytics_enabled=False) as demo:
        gr.Markdown(
            "# NutriWise AI\n"
            "Describe a meal in your own words and get an estimate of its calories and macros. "
            "Numbers are **approximate**; the *source* and *note* show how each estimate was made."
        )
        summary = gr.Markdown()

        with gr.Row():
            with gr.Column(scale=3):
                meal_box = gr.Textbox(
                    label="What did you eat?",
                    placeholder="e.g. 2 rotis, a bowl of dal and a glass of milk",
                    lines=1,  # single line, so pressing Enter submits (multi-line boxes insert a newline)
                )
                with gr.Row():
                    estimate_btn = gr.Button("Estimate", variant="primary")
                    save_btn = gr.Button("Save to log")
                gr.Examples(EXAMPLES, inputs=meal_box, label="Try an example")
            with gr.Column(scale=2):
                result_json = gr.JSON(label="Latest estimate")

        table = gr.Dataframe(headers=HEADERS, label="Today's meals", interactive=False, wrap=True)
        with gr.Row():
            delete_box = gr.Textbox(label="Meal ID to delete", placeholder="Click a row above, or type its ID", scale=3)
            delete_btn = gr.Button("Delete meal", variant="stop", scale=1)

        # Per-browser-tab memory of the last estimate (not shared between users).
        latest = gr.State(None)

        # Wiring: event -> handler(inputs) -> outputs
        for trigger in (estimate_btn.click, meal_box.submit):  # button OR Enter key
            trigger(handle_estimate, inputs=meal_box, outputs=[result_json, latest])
        save_btn.click(handle_save, inputs=[meal_box, latest], outputs=[result_json, latest, meal_box, summary, table])
        delete_btn.click(handle_delete, inputs=delete_box, outputs=[delete_box, summary, table])
        table.select(handle_row_click, outputs=delete_box)
        demo.load(refresh, outputs=[summary, table])  # fresh data on every page (re)load

    return demo


def launch(share: bool = False, port: int = 7860, host: str = "127.0.0.1", open_browser: bool = False):
    """Build and start the app. Works from the command line and inside Jupyter."""
    demo = build_ui()
    demo.launch(
        share=share,              # True = temporary public *.gradio.live link
        server_name=host,         # 127.0.0.1 = only this computer can connect
        server_port=port,
        inbrowser=open_browser,
        theme=gr.themes.Soft(),   # Gradio 6: theme goes here, not in gr.Blocks()
    )
    return demo
