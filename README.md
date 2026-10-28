# NutriWise AI — LLM-Powered Calorie Tracker

Describe a meal in plain language ("2 rotis, a bowl of dal and a glass of milk") and get an
estimate of its calories, protein, carbs and fat. Save meals to a daily log and see today's total.

Estimates come from a **multi-stage pipeline** that tries the cheapest, most reliable source first
and always tells you where each number came from.

```
meal text ──► parser ──► 1. Local food table   instant, offline (~30 home-cooked / Indian foods)
                           │ unknown food
                           ▼
                         2. Nutrition APIs      API Ninjas → USDA FoodData Central → Open Food Facts
                           │ not found / offline
                           ▼
                         3. LLMs                Gemini Flash → Gemini Flash-Lite → Groq → OpenRouter
                           │ all unavailable
                           ▼
                         4. Placeholder         rough, clearly labelled guess — the app never crashes
                           │
                           ▼
          NutritionEstimate (Pydantic) ──► Gradio UI ──► data/meals.json
```

## Requirements

- Python 3.10 or newer
- At least one LLM key: **Gemini** (free at <https://aistudio.google.com>) or Groq / OpenRouter
- Optional: a free USDA key (<https://fdc.nal.usda.gov/api-key-signup>). Without one the public
  `DEMO_KEY` is used, which allows only 10 requests per hour.

## Setup

```bash
cd nutriwise
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your keys into .env
```

`.env` holds your private keys and is never committed or packaged. `.env.example` is the shareable template.

## Run

| How | Command |
|---|---|
| Web app | `python main.py` then open <http://127.0.0.1:7860> |
| Open browser automatically | `python main.py --open` |
| Other port / detailed logs | `python main.py --port 8000 --debug` |
| Temporary public link | `python main.py --share` (anyone with the link uses your API quota) |
| Jupyter | open `notebooks/nutriwise_demo.ipynb`, or `from app.ui import launch; launch()` |

**Using the app:** type a meal → **Estimate** (or press Enter) → check the JSON panel → **Save to log**.
To delete a meal, click its row in the table and press **Delete meal**.

## Tests

```bash
pytest              # 71 unit tests: offline, no API calls, about 10 seconds
pytest -m live      # 2 smoke tests against the real Gemini and USDA APIs (uses a little quota)
```

<img width="1563" height="847" alt="Screenshot 2026-10-28 at 8 12 59 AM" src="https://github.com/user-attachments/assets/6dc24147-3d86-4826-8abd-1dee66995e92" />



## Project structure

```
nutriwise/
├── app/
│   ├── schema.py       Pydantic models: FoodItem, NutritionEstimate (the shared output contract)
│   ├── food_table.py   Stage 1: local food table, aliases, regex meal parser
│   ├── apis.py         Stage 2: API Ninjas / USDA / Open Food Facts, relevance matching
│   ├── llm.py          Stage 3: Gemini / Groq / OpenRouter with structured JSON and retries
│   ├── estimator.py    estimate_meal(): runs the stages in order, placeholder fallback
│   ├── storage.py      data/meals.json: save, delete, daily totals (atomic, thread-safe)
│   └── ui.py           Gradio layout, display helpers, button handlers, launch()
├── tests/              pytest suite (conftest.py blocks network + uses a temp data file)
├── notebooks/          walkthrough notebook
├── data/               meals.json is created here on first save
├── main.py             command-line entry point
├── package.py          builds the submission zip (excludes keys and personal data)
├── requirements.txt
└── .env.example
```

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini (first LLM tried) |
| `GROQ_API_KEY` | Groq (second LLM) |
| `OPENROUTER_API_KEY` | OpenRouter (third LLM, free models) |
| `USDA_API_KEY` | USDA FoodData Central (else `DEMO_KEY`) |
| `API_NINJAS_KEY` | API Ninjas (the free tier hides calories, so it's usually skipped) |
| `GEMINI_MODEL`, `GEMINI_LITE_MODEL`, `GROQ_MODEL`, `OPENROUTER_MODEL` | Override model names when providers retire them |

## Saved data format

`data/meals.json` is a list of records, newest first:

```json
{
  "id": "9497dd8b6ad343a1aa96947c1d3836a9",
  "date": "2026-10-28",
  "created_at": "2026-10-28T07:28:33-04:00",
  "input": "2 rotis and dal",
  "name": "2 piece roti, 1 bowl dal",
  "calories": 420.0, "protein": 15.0, "carbs": 60.0, "fat": 12.0,
  "note": "Typical home-cooked portions from the local table.",
  "source": "local_table"
}
```

## Packaging for submission

```bash
python package.py
```

Creates `NutriWise-AI-submission.zip` next to the project folder. It excludes `.env`, `.venv`,
caches and your personal `data/meals.json`, and refuses to build if any real API key value is
found in the files being packaged.

## Known limitations

- Estimates are approximate. Two LLMs gave 650 and 752 kcal for the same pav bhaji.
- Stage 2 guesses portion weights per unit (a "bowl" is about 150 g), not per food.
- One unknown food sends the whole meal to the next stage; there's no per-item routing to the LLM.
- The parser splits on "with", so "coffee with milk" is counted as coffee plus a glass of milk.
- A JSON file suits one user; many users or years of data would need a database such as SQLite.
- LLM model names change often; override them in `.env` when a provider retires one.
