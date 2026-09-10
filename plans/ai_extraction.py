"""
B2: real structured extraction using an LLM (Gemini -- has a genuinely
free tier, unlike Anthropic/OpenAI), instead of the old fixed regex
patterns in structured_extraction.py which only ever caught
RTO/RPO/emails/phones -- and only when phrased exactly like "RTO: 4
hours". A real BIA/BC plan has far more in it (business functions,
impact ratings, systems + per-system RTO/RPO, dependencies, resource
ramp-up, contacts) and companies won't all use the same template, so
this doesn't look for fixed columns/headings -- it asks the model to
read the document and pull out whatever's actually there.

Falls back to nothing (None) if GEMINI_API_KEY isn't configured, or if
anything about the call/response goes wrong -- plans/intake.py then
uses the old regex extraction instead, so a missing key or a flaky API
call never blocks a plan upload.
"""

import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

# What we ask the model to find. Based on a real sample BIA template
# (contacts, business functions, impact ratings, systems w/ RTO+RPO,
# dependencies, resource ramp-up) -- but phrased as "whatever you find"
# rather than fixed columns, since a different company's plan may be
# structured completely differently, or be missing sections entirely.
_EXTRACTION_PROMPT = """You are extracting structured data from a business continuity / \
business impact analysis (BIA) plan. The document text follows below. \
Read it and pull out every relevant field you can find -- do not assume \
a fixed template, different organizations lay these out differently.

Return ONLY a single JSON object (no other text, no markdown fences) with this shape. \
Omit a field entirely if the document doesn't contain it -- do not invent values.

{{
  "rto": ["<overall or per-system RTO values as written, e.g. \\"4 hours\\">"],
  "rpo": ["<overall or per-system RPO values as written>"],
  "contacts": [{{"name": "", "role": "", "phone": "", "email": ""}}],
  "business_functions": ["<critical business activity/function names>"],
  "systems": [
    {{"name": "", "internal_or_external": "", "rto": "", "rpo": "", "data_required": "", "manual_workaround": ""}}
  ],
  "dependencies": [{{"name": "", "type": "", "impact_if_lost": ""}}],
  "impact_ratings": [{{"function": "", "category": "", "rating": ""}}],
  "resource_ramp_up": [{{"task": "", "notes": ""}}]
}}

Document text:
---
{text}
---"""

# The model has a real context limit -- keep this well under it. A BIA
# is a business document, not a novel; if a plan is genuinely larger
# than this, truncating still lets the model see most of it rather than
# failing the whole extraction outright.
_MAX_CHARS = 60_000


def extract_with_ai(text: str) -> dict | None:
    """
    Returns a dict shaped like structured_extraction.extract_structured_fields's
    output, plus the richer fields above -- or None if AI extraction isn't
    available/didn't work, so the caller can fall back to the regex version.
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key or not text:
        return None

    prompt = _EXTRACTION_PROMPT.format(text=text[:_MAX_CHARS])

    try:
        response = requests.post(
            GEMINI_API_URL,
            params={"key": api_key},
            headers={"content-type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("AI plan extraction request failed")
        return None

    body = response.json()
    try:
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected Gemini API response shape: %s", body)
        return None

    return _parse_json_response(raw_text)


def _parse_json_response(raw_text: str) -> dict | None:
    # The model is asked for JSON only, but strip markdown fences
    # defensively in case it wraps the response anyway.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Could not parse AI extraction response as JSON: %s", raw_text[:500])
        return None

    if not isinstance(data, dict):
        return None

    # Normalize so downstream code (build_bia_ready_card etc.) can rely
    # on these keys always existing, even if the model omitted them.
    data.setdefault("rto", [])
    data.setdefault("rpo", [])
    data.setdefault("contacts", [])
    data.setdefault("business_functions", [])
    data.setdefault("systems", [])
    data.setdefault("dependencies", [])
    data.setdefault("impact_ratings", [])
    data.setdefault("resource_ramp_up", [])
    # "emails"/"phones" keys are what the rest of the app (contact
    # freshness checks, the BIA card) already reads -- derive them from
    # the richer "contacts" list so nothing downstream has to change.
    data["emails"] = sorted({c["email"] for c in data["contacts"] if c.get("email")})
    data["phones"] = sorted({c["phone"] for c in data["contacts"] if c.get("phone")})
    return data
