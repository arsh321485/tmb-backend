"""
Reusable OpenAI text-generation call -- second real backup for
plans/scenario_generator.py (Agent 2), tried after NVIDIA, instead of
gemini_client.py there. Confirmed live: Gemini's free tier returned a
real HTTP 429 (rate limit exceeded) during heavy same-day testing,
which meant NVIDIA failing (timeout) AND Gemini failing (rate limit)
at the same moment, with no third option -- every "Try again" click
hit the same two exhausted/struggling providers. A different provider
with its own separate quota is a real second option, not just another
retry against whatever's already failing.

Same calling convention as gemini_client.generate() (prompt in,
text out, None on any failure, never raises) so a caller can swap
between them without changing anything else.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

_MAX_ATTEMPTS = 2
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def generate(prompt: str, *, system: str = "", timeout: int = 90) -> str | None:
    """
    Returns the model's text reply, or None if the key isn't configured
    or every attempt failed -- never raises.
    """
    api_key = settings.OPENAI_API_KEY
    if not api_key or not prompt:
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                OPENAI_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
                json={
                    "model": settings.OPENAI_MODEL,
                    "messages": messages,
                    "max_tokens": 8192,
                    "response_format": {"type": "json_object"},
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
                    logger.exception("OpenAI fallback request failed (non-retryable)")
                    return None
                try:
                    return response.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    logger.warning("Unexpected OpenAI response shape: %s", response.text[:500])
                    return None
            last_error = f"HTTP {response.status_code}"

        if attempt < _MAX_ATTEMPTS:
            logger.warning("OpenAI fallback call failed (attempt %s/%s): %s -- retrying", attempt, _MAX_ATTEMPTS, last_error)
            time.sleep(attempt)

    logger.error("OpenAI fallback failed after %s attempts: %s", _MAX_ATTEMPTS, last_error)
    return None
