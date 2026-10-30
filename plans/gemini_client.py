"""
Reusable Gemini text-generation call, for anything that needs a generic
prompt answered -- not specific to plan BIA extraction (see
ai_extraction.py for that older, narrower use of the same API). Built
as the fast/reliable fallback for plans/resilience_map.py: NVIDIA's
endpoint is sir's chosen model and tried first, but it sits on a
shared/free tier that's sometimes slow or briefly down -- Gemini has
proven fast and reliable for structured extraction elsewhere in this
codebase, so it's a real second attempt, not a weaker one.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

_MAX_ATTEMPTS = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def generate(prompt: str, *, timeout: int = 45) -> str | None:
    """
    Returns the model's text reply, or None if the key isn't configured
    or every attempt failed -- never raises.

    Retries like nvidia_client.py does -- this is the LAST line of
    defense (NVIDIA already failed 3 times before this runs), so a
    single untried attempt here meant a brief Gemini hiccup at the
    exact same moment could still fail the whole extraction (confirmed
    live: happened to a real upload). 3 tries here closes that gap.
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key or not prompt:
        return None

    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                GEMINI_API_URL,
                params={"key": api_key},
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code not in _RETRY_STATUS_CODES:
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    logger.exception("Gemini fallback request failed (non-retryable)")
                    return None
                try:
                    return response.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError):
                    logger.warning("Unexpected Gemini response shape: %s", response.text[:500])
                    return None
            last_error = f"HTTP {response.status_code}"

        if attempt < _MAX_ATTEMPTS:
            logger.warning("Gemini fallback call failed (attempt %s/%s): %s -- retrying", attempt, _MAX_ATTEMPTS, last_error)
            time.sleep(attempt)

    logger.error("Gemini fallback failed after %s attempts: %s", _MAX_ATTEMPTS, last_error)
    return None
