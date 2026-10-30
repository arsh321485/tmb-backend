"""
Phase 1 (Read) backend AI -- NVIDIA NIM chat completions, used for the
AI-generated pieces of the Plan Builder (service catalogue proposals,
BIA interview follow-up questions, starter-plan drafting) and other
Phase 1/2 data-generation work going forward.

Separate from plans/ai_extraction.py's Gemini call, which is a
different, already-working path (regex-style structured extraction
from an uploaded document). This module is for the newer
generate-text-from-a-prompt work the NVIDIA model is being used for.

Same fallback discipline as ai_extraction.py: returns None (never
raises) if the key isn't configured or the call fails in any way, so a
missing key or a flaky API never blocks the admin flow.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

_MAX_ATTEMPTS = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def generate(
    prompt: str, *, system: str = "", max_tokens: int = 4096, temperature: float = 0.6, reasoning_budget: int | None = None
) -> str | None:
    """
    Sends a single user prompt (plus optional system prompt) to the
    configured NVIDIA model and returns the model's final text reply
    (not its reasoning), or None if the key isn't set or the call
    didn't succeed after retries.

    reasoning_budget is only relevant for a reasoning model (e.g. the
    nemotron-nano "-reasoning" variant), whose response has a separate
    "reasoning_content" field (the model's scratch thinking) alongside
    "content" (the actual answer) -- without it, a long/structured
    prompt can run out of max_tokens mid-reasoning and leave "content"
    holding a truncated reasoning dump instead of the real answer
    (confirmed live). The default (non-reasoning "bolt") model has no
    such field, so it's left out of the payload unless passed explicitly.
    """
    api_key = settings.NVIDIA_API_KEY
    if not api_key or not prompt:
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "model": settings.NVIDIA_MODEL,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": temperature,
        "top_p": 0.95,
    }
    if reasoning_budget is not None:
        payload["reasoning_budget"] = reasoning_budget

    response = _call_with_retries(payload, api_key)
    if response is None:
        return None

    try:
        message = response.json()["choices"][0]["message"]
        content = (message.get("content") or "").strip()
        if not content:
            logger.warning("NVIDIA response had no final content (still reasoning?): %s", response.text[:500])
            return None
        return content
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected NVIDIA API response shape: %s", response.text[:500])
        return None


def _call_with_retries(payload: dict, api_key: str):
    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # This is a shared/public endpoint and genuinely slow under
            # load (confirmed live: timed out twice at 60s on a real
            # upload) -- 120s gives a loaded reasoning model room to
            # actually finish instead of retrying into the same wall.
            response = requests.post(
                NVIDIA_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code not in _RETRY_STATUS_CODES:
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    logger.exception("NVIDIA API request failed (non-retryable)")
                    return None
                return response
            last_error = f"HTTP {response.status_code}"

        if attempt < _MAX_ATTEMPTS:
            logger.warning(
                "NVIDIA API call failed (attempt %s/%s): %s -- retrying", attempt, _MAX_ATTEMPTS, last_error
            )
            time.sleep(attempt)

    logger.error("NVIDIA API call failed after %s attempts: %s", _MAX_ATTEMPTS, last_error)
    return None
