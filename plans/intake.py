"""
B1: drag-and-drop plan intake. No upload screen, no import wizard -- the
user just drops a DOCX/PDF/XLSX into a DM with the app, and this reacts to
Slack's `message` event (channel_type "im") that carries the file.
"""

import logging

import requests

from .ai_extraction import extract_with_ai
from .contact_freshness import check_contacts, gaps_from_contact_checks
from .control_mapping import map_controls
from .models import ALLOWED_EXTENSIONS, STATUS_FAILED, STATUS_PARSED, Plan
from .parsing import PlanParsingError, extract_text
from .gap_review import find_gaps
from .resilience_map import extract_resilience_map
from .structured_extraction import extract_structured_fields
from .versioning import assign_version

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


def _post_message(channel: str, text: str, bot_token: str) -> None:
    if not bot_token:
        logger.warning("Can't post to Slack -- no bot token for this workspace.")
        return
    requests.post(
        f"{SLACK_API_BASE}/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel, "text": text},
        timeout=10,
    )


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def handle_dm_message_event(event: dict, team_id: str, bot_token: str) -> None:
    """
    event is a Slack `message` event (see Events API: message.im). Only
    acts on ones carrying files; ignores plain text DMs. `team_id`/
    `bot_token` identify which client workspace this came from -- every
    Slack API call and saved record below is scoped to that workspace only.
    """
    files = event.get("files") or []
    if not files:
        return

    channel_id = event.get("channel", "")
    user_id = event.get("user", "")

    for f in files:
        ingest_one_file(f, channel_id, user_id, team_id, bot_token)


def ingest_one_file(
    slack_file: dict,
    channel_id: str,
    user_id: str,
    team_id: str,
    bot_token: str,
    post_confirmation: bool = True,
) -> "Plan | None":
    """
    Downloads and parses one Slack file object into a Plan. Public (not
    just called from the DM-drop path above) so any other real upload
    entry point (a future file-picker modal, etc.) can reuse the exact
    same real parsing pipeline instead of duplicating it --
    `post_confirmation=False` for a caller that shows its own result
    card instead of this generic "Got it, uploaded and parsed" message.
    """
    filename = slack_file.get("name", "unnamed")
    extension = _extension_of(filename)

    if extension not in ALLOWED_EXTENSIONS:
        _post_message(
            channel_id,
            f":warning: `{filename}` isn't a supported plan format. "
            "Drop a DOCX, PDF or XLSX file instead.",
            bot_token,
        )
        return None

    download_url = slack_file.get("url_private_download") or slack_file.get("url_private")
    if not download_url:
        _post_message(channel_id, f":warning: Couldn't read `{filename}` from Slack.", bot_token)
        return None

    try:
        resp = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to download plan file %s from Slack", filename)
        _post_message(channel_id, f":warning: Couldn't download `{filename}` -- try again?", bot_token)
        return None

    plan = Plan(
        filename=filename,
        file_extension=extension,
        uploaded_by_slack_user_id=user_id,
        slack_team_id=team_id,
        slack_channel_id=channel_id,
    )
    plan.file_data.put(resp.content, content_type=slack_file.get("mimetype", ""))
    is_new_version = assign_version(plan)

    try:
        plan.extracted_text = extract_text(resp.content, extension)
        # Try real AI extraction first (reads whatever fields the document
        # actually has -- RTO/RPO, contacts, systems, dependencies, impact
        # ratings, resource ramp-up -- regardless of template/format).
        # Falls back to the old fixed regex patterns if no API key is set
        # or the AI call fails, so a plan upload never breaks either way.
        plan.structured_data = extract_with_ai(plan.extracted_text) or extract_structured_fields(
            plan.extracted_text
        )
        # AI extraction's "contacts" (name/email/phone dicts) checks by
        # name when there's no email -- the regex fallback only ever has
        # "emails" (plain strings), which check_contacts also accepts.
        contacts_to_check = plan.structured_data.get("contacts")
        if contacts_to_check is None:
            contacts_to_check = plan.structured_data.get("emails") or []
        plan.contact_checks = check_contacts(contacts_to_check, bot_token)
        plan.control_mapping = map_controls(plan.extracted_text)
        plan.gaps = find_gaps(plan.structured_data) + gaps_from_contact_checks(
            plan.contact_checks
        )
        # Phase 1 (Read) -- the real resilience map (per-service RTO/RPO/
        # MTPD + dependencies), via NVIDIA. Restricted to whoever's
        # assigned as the real "Plans & BIA owner" (cards/admins_v2_data.py)
        # -- if someone else uploads, the old legacy extraction above
        # still runs (so the file is still saved/parsed), but the real
        # Phase 1 map is skipped for them; not a failure, so a plan
        # upload never breaks either way.
        from cards.persistence_v2 import get_module_owner

        owner_id = get_module_owner(team_id, "plans_bia")
        is_owner_assigned = bool(owner_id)
        is_authorized = (not is_owner_assigned) or (owner_id == user_id)

        if is_authorized:
            resilience_map = extract_resilience_map(plan.extracted_text)
            if resilience_map:
                plan.resilience_map = resilience_map
                plan.resilience_map_status = "proposed"
        plan.status = STATUS_PARSED
    except PlanParsingError as exc:
        plan.status = STATUS_FAILED
        plan.parse_error = str(exc)
    except Exception:
        logger.exception("Unexpected error extracting text from %s", filename)
        plan.status = STATUS_FAILED
        plan.parse_error = "Unexpected error while reading the file."

    plan.save()

    if not post_confirmation:
        return plan

    version_note = (
        f" This is *version {plan.version}* -- since the plan changed, "
        "a re-test is recommended once exercises are wired up to plans."
        if is_new_version
        else ""
    )

    if plan.status == STATUS_PARSED:
        if is_owner_assigned and not is_authorized:
            _post_message(
                channel_id,
                f":inbox_tray: Got it -- *{filename}* saved.{version_note} "
                ":lock: Only the assigned *Plans & BIA owner* can generate and confirm "
                "the resilience map for this workspace -- ask your admin to assign you "
                "in the Admins card if this should be your job.",
                bot_token,
            )
        elif plan.resilience_map:
            # The real resilience map card (Phase 1, A10) replaces the
            # old regex-era summary text below -- it shows the same
            # "what did we find" information, properly structured and
            # with a real confirm step, so the old verbose text message
            # was dropped (sir's call: it was leftover from before this
            # plan existed and only confused what's actually new).
            from cards.resilience_map_v2 import send_card

            send_card(plan, channel_id, bot_token)
        else:
            # No resilience map -- the NVIDIA call is on a shared/slow
            # endpoint and sometimes genuinely times out even when the
            # document is fine (confirmed live: the exact same file
            # worked moments later on retry). A Retry button costs
            # nothing when things are healthy and saves a re-upload
            # when they aren't.
            from cards.resilience_map_v2 import send_retry_card

            send_retry_card(plan, channel_id, bot_token, version_note)
    else:
        _post_message(
            channel_id,
            f":inbox_tray: Got it -- *{filename}* uploaded and saved, but "
            f"I couldn't read its text ({plan.parse_error}). The file is "
            "still stored.",
            bot_token,
        )

    return plan
