"""
B1: drag-and-drop plan intake. No upload screen, no import wizard -- the
user just drops a DOCX/PDF/XLSX into a DM with the app, and this reacts to
Slack's `message` event (channel_type "im") that carries the file.
"""

import logging

import requests
from django.conf import settings

from .models import ALLOWED_EXTENSIONS, STATUS_FAILED, STATUS_PARSED, Plan
from .parsing import PlanParsingError, extract_text
from .structured_extraction import extract_structured_fields

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


def _post_message(channel: str, text: str) -> None:
    if not settings.SLACK_BOT_TOKEN:
        logger.warning("Can't post to Slack -- SLACK_BOT_TOKEN not configured.")
        return
    requests.post(
        f"{SLACK_API_BASE}/chat.postMessage",
        headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
        json={"channel": channel, "text": text},
        timeout=10,
    )


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _summarize(structured: dict) -> str:
    """One-line summary of what pattern-matching found, for the Slack reply."""
    found = []
    if structured.get("rto"):
        found.append(f"RTO: {', '.join(structured['rto'])}")
    if structured.get("rpo"):
        found.append(f"RPO: {', '.join(structured['rpo'])}")
    if structured.get("emails"):
        found.append(f"{len(structured['emails'])} contact email(s)")
    if structured.get("sections"):
        found.append(f"{len(structured['sections'])} section(s)")

    if not found:
        return (
            "No RTO/RPO targets, contacts or sections detected automatically -- "
            "full structured analysis (roles, triggers, escalation paths) "
            "still needs real NLP, this is pattern-matching only."
        )
    return "Found so far: " + "; ".join(found) + "."


def handle_dm_message_event(event: dict) -> None:
    """
    event is a Slack `message` event (see Events API: message.im). Only
    acts on ones carrying files; ignores plain text DMs.
    """
    files = event.get("files") or []
    if not files:
        return

    channel_id = event.get("channel", "")
    user_id = event.get("user", "")

    for f in files:
        _ingest_one_file(f, channel_id, user_id)


def _ingest_one_file(slack_file: dict, channel_id: str, user_id: str) -> None:
    filename = slack_file.get("name", "unnamed")
    extension = _extension_of(filename)

    if extension not in ALLOWED_EXTENSIONS:
        _post_message(
            channel_id,
            f":warning: `{filename}` isn't a supported plan format. "
            "Drop a DOCX, PDF or XLSX file instead.",
        )
        return

    download_url = slack_file.get("url_private_download") or slack_file.get("url_private")
    if not download_url:
        _post_message(channel_id, f":warning: Couldn't read `{filename}` from Slack.")
        return

    try:
        resp = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to download plan file %s from Slack", filename)
        _post_message(channel_id, f":warning: Couldn't download `{filename}` -- try again?")
        return

    plan = Plan(
        filename=filename,
        file_extension=extension,
        uploaded_by_slack_user_id=user_id,
        slack_channel_id=channel_id,
    )
    plan.file_data.put(resp.content, content_type=slack_file.get("mimetype", ""))

    try:
        plan.extracted_text = extract_text(resp.content, extension)
        plan.structured_data = extract_structured_fields(plan.extracted_text)
        plan.status = STATUS_PARSED
    except PlanParsingError as exc:
        plan.status = STATUS_FAILED
        plan.parse_error = str(exc)
    except Exception:
        logger.exception("Unexpected error extracting text from %s", filename)
        plan.status = STATUS_FAILED
        plan.parse_error = "Unexpected error while reading the file."

    plan.save()

    if plan.status == STATUS_PARSED:
        word_count = len(plan.extracted_text.split())
        _post_message(
            channel_id,
            f":inbox_tray: Got it -- *{filename}* uploaded and parsed "
            f"(~{word_count} words). {_summarize(plan.structured_data)}",
        )
    else:
        _post_message(
            channel_id,
            f":inbox_tray: Got it -- *{filename}* uploaded and saved, but "
            f"I couldn't read its text ({plan.parse_error}). The file is "
            "still stored.",
        )
