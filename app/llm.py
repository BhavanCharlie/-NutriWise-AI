"""Stage 3 of the pipeline: ask an LLM to estimate the meal.

Providers are tried in order: Gemini -> Groq -> OpenRouter. A provider is
skipped if its key is missing, and any error (bad key, timeout, quota,
invalid JSON, failed validation) moves on to the next one.
"""

import json
import logging
import os
import re
import time

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.schema import NutritionEstimate

load_dotenv()
log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20  # LLMs are slower than nutrition APIs

# Model names change often, so each can be overridden from .env.
# "gemini-flash-latest" is an alias Google keeps pointed at the current Flash model.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_LITE_MODEL = os.getenv("GEMINI_LITE_MODEL", "gemini-flash-lite-latest")  # smaller, less often overloaded
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")


class LLMNutrition(BaseModel):
    """What we ask the LLM for. Same as NutritionEstimate minus `source`:
    the LLM shouldn't decide where the data came from, our code knows that."""

    name: str = Field(description="Short name of the whole meal")
    calories: float = Field(description="Total kcal for the whole meal")
    protein: float = Field(description="Total protein in grams")
    carbs: float = Field(description="Total carbohydrates in grams")
    fat: float = Field(description="Total fat in grams")
    note: str = Field(description="One sentence: portion sizes assumed and how uncertain the estimate is")


SYSTEM_PROMPT = """You are a careful nutritionist estimating calories for a calorie-tracking app.
The user describes a meal in everyday language. It may be a home-cooked or Indian dish.

Rules:
- Estimate TOTALS for everything described, not per 100 g.
- If no quantity is given, assume one typical home serving and say so in the note.
- Use realistic values for home cooking (normal oil/ghee), not restaurant or diet versions.
- Protein, carbs and fat should roughly agree with calories (4/4/9 kcal per gram).
- If the input is not food, return 0 for every number and explain in the note.
- Respond with JSON only, matching this schema:
""" + json.dumps(LLMNutrition.model_json_schema()["properties"], indent=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict:
    """Pull a JSON object out of an LLM reply, even if wrapped in ```json fences or prose."""
    match = re.search(r"\{.*\}", text, re.DOTALL)  # DOTALL lets . match newlines
    if not match:
        raise ValueError("no JSON object in reply")
    return json.loads(match.group())


# Status codes that mean "busy, try again soon" rather than "you did something wrong".
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
# Seconds to wait before each retry. One retry keeps the UI responsive: with
# more providers behind this one, moving on beats waiting on a busy model.
RETRY_DELAYS = [2]


def _status_of(err: Exception) -> int | None:
    """Find the HTTP status code on either a google-genai error or a requests error."""
    if isinstance(getattr(err, "code", None), int):  # google.genai.errors.APIError
        return err.code
    response = getattr(err, "response", None)  # requests.HTTPError
    return getattr(response, "status_code", None)


def _with_retries(ask, meal: str) -> dict:
    """Call ask(meal); on a transient error wait and retry. Permanent errors raise at once."""
    for delay in RETRY_DELAYS + [None]:
        try:
            return ask(meal)
        except Exception as err:
            if delay is None or _status_of(err) not in TRANSIENT_STATUS:
                raise
            log.info("%s busy (status %s), retrying in %ss", ask.__name__, _status_of(err), delay)
            time.sleep(delay)


def _to_estimate(raw: dict, source: str) -> NutritionEstimate:
    """Validate the LLM's dict with OUR schema (cleans '250 kcal', rejects negatives).

    0 kcal is allowed on purpose: it's the prompt's answer for "not food".
    """
    return NutritionEstimate(**{**raw, "source": source})


# ---------------------------------------------------------------------------
# Providers: each takes the meal text and returns a raw dict, or raises
# ---------------------------------------------------------------------------
def ask_gemini(meal: str, model: str = GEMINI_MODEL) -> dict:
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000),  # milliseconds
    )
    response = client.models.generate_content(
        model=model,
        contents=meal,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=LLMNutrition,  # Gemini is *forced* to return this shape
            temperature=0.2,  # low = more consistent numbers between runs
        ),
    )
    return _extract_json(response.text)


def ask_gemini_lite(meal: str) -> dict:
    return ask_gemini(meal, model=GEMINI_LITE_MODEL)


def _ask_openai_compatible(url: str, key: str, model: str, meal: str) -> dict:
    """Groq and OpenRouter both speak the OpenAI chat-completions format."""
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": meal},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _extract_json(response.json()["choices"][0]["message"]["content"])


def ask_groq(meal: str) -> dict:
    return _ask_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"], GROQ_MODEL, meal
    )


def ask_openrouter(meal: str) -> dict:
    return _ask_openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], OPENROUTER_MODEL, meal
    )


# (source name, env var holding the key, function)
PROVIDERS = [
    ("gemini", "GEMINI_API_KEY", ask_gemini),
    ("gemini", "GEMINI_API_KEY", ask_gemini_lite),
    ("groq", "GROQ_API_KEY", ask_groq),
    ("openrouter", "OPENROUTER_API_KEY", ask_openrouter),
]


def estimate_with_llm(meal: str) -> NutritionEstimate | None:
    """Stage 3: try each configured LLM in order; None if all fail or none are configured."""
    for source, key_name, ask in PROVIDERS:
        if not os.getenv(key_name):
            log.info("Skipping %s: %s not set", source, key_name)
            continue
        try:
            return _to_estimate(_with_retries(ask, meal), source)
        except (ValidationError, ValueError, KeyError) as err:
            log.warning("%s gave an unusable answer: %s", source, err)
        except Exception as err:  # network, auth, quota... SDKs raise many types
            # Keys travel in headers here (not the URL), so the message is safe to log.
            log.warning("%s failed: %s: %s", source, type(err).__name__, str(err)[:200])
    return None
