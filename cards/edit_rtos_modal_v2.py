"""
"Does this look right?" on Upload & Analysis -- lets the admin correct
a wrong RTO the AI extraction got wrong from a real uploaded document,
instead of only being able to accept-or-reject the whole thing.

Was a free-text field ("3 days", "1 month", whatever the document
actually said), then a fixed list of whole preset RTOs -- sir then
asked for a number entered by the admin (1, 2, 3, 4...) plus a
dropdown for the unit (Minutes/Hours/Days/Weeks/Months), so any value
is possible (e.g. "6 Hours") while the unit wording is still always
one the RTO parser (plans/threat_ranking.py's _rto_to_hours)
recognizes -- a free-typed unit is what caused the original sort bug.
"""

import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_edit_rtos_modal"

# Modal views allow up to 100 blocks; two input blocks (number + unit)
# per service keeps this comfortably inside that even for an org with
# many services.
MAX_SERVICES_IN_MODAL = 40

UNIT_OPTIONS = ["Minutes", "Hours", "Days", "Weeks", "Months"]

_UNIT_CANON = {
    "hour": "Hours", "hours": "Hours", "hr": "Hours", "hrs": "Hours",
    "minute": "Minutes", "minutes": "Minutes", "min": "Minutes", "mins": "Minutes",
    "day": "Days", "days": "Days",
    "week": "Weeks", "weeks": "Weeks",
    "month": "Months", "months": "Months",
}


def _parse_number_unit(rto_text: str) -> tuple[str | None, str | None]:
    """Splits a real document's free-text RTO into (number, unit) so
    the number field and unit dropdown can both open pre-filled with
    what the AI actually extracted. ("Immediate", None) when the text
    reads as immediate/zero-time rather than a number+unit."""
    if not rto_text:
        return None, None
    t = rto_text.lower()
    if "immediate" in t or "near zero" in t or "real-time" in t or "real time" in t or "asap" in t:
        return "Immediate", None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|hrs|hr\b|minute|minutes|mins|min\b|day|days|week|weeks|month|months)", t)
    if not match:
        return None, None
    value, unit = match.groups()
    return value, _UNIT_CANON.get(unit)


def _sorted_services(plan) -> list:
    """Shortest RTO (most urgent) first -- same order and same sort key
    as bia_upload_v2_data.py's _services_blocks, so the list the admin
    sees here matches what they saw on the main screen. Used by BOTH
    build_modal_view and handle_submission so the two stay in the same
    order -- handle_submission matches edited values back to services
    by index, so a mismatch here would silently save the wrong RTO
    against the wrong service."""
    from plans.threat_ranking import _rto_to_hours

    services = (plan.resilience_map or {}).get("services") or []

    def _sort_key(svc: dict) -> float:
        hours = _rto_to_hours(svc.get("rto") or "")
        return hours if hours is not None else float("inf")

    return sorted(services, key=_sort_key)


def build_modal_view(plan, channel_id: str = "", message_ts: str = "") -> dict:
    services = _sorted_services(plan)
    services = services[:MAX_SERVICES_IN_MODAL]

    blocks = []
    for idx, svc in enumerate(services):
        name = (svc.get("name") or "Unnamed service")[:150]
        number, unit = _parse_number_unit(svc.get("rto") or "")
        is_immediate = number == "Immediate"

        unit_options = [{"text": {"type": "plain_text", "text": "Immediate"}, "value": "Immediate"}] + [
            {"text": {"type": "plain_text", "text": u}, "value": u} for u in UNIT_OPTIONS
        ]
        unit_element = {
            "type": "static_select",
            "action_id": "value",
            "placeholder": {"type": "plain_text", "text": "Unit"},
            "options": unit_options,
        }
        initial_unit_label = "Immediate" if is_immediate else unit
        if initial_unit_label:
            unit_element["initial_option"] = {"text": {"type": "plain_text", "text": initial_unit_label}, "value": initial_unit_label}

        number_element = {
            "type": "plain_text_input",
            "action_id": "value",
            "placeholder": {"type": "plain_text", "text": "e.g. 4"},
        }
        if number and not is_immediate:
            number_element["initial_value"] = number

        blocks.append({"type": "input", "block_id": f"rto_num__{idx}", "optional": True, "label": {"type": "plain_text", "text": (name[:60] or "Service") + " — number"}, "element": number_element})
        blocks.append({"type": "input", "block_id": f"rto_unit__{idx}", "optional": True, "label": {"type": "plain_text", "text": (name[:60] or "Service") + " — unit"}, "element": unit_element})

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"plan_id": str(plan.id), "channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Edit RTOs"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def open_modal(trigger_id: str, plan, bot_token: str, channel_id: str = "", message_ts: str = "") -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(plan, channel_id, message_ts)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    from .bia_upload_v2_data import build_bia_upload_card
    from .nav_v2 import with_nav_bar_v2
    from .slack_client import SlackApiError, _call
    from plans.models import Plan

    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        return
    plan = Plan.objects(id=meta.get("plan_id", "")).first() if meta.get("plan_id") else None
    if not plan:
        return

    values = view.get("state", {}).get("values", {})
    all_services = _sorted_services(plan)
    shown_services = all_services[:MAX_SERVICES_IN_MODAL]
    # Anything beyond the modal's own cap was never shown/editable --
    # keep it as-is rather than silently dropping it on save.
    remainder_services = all_services[MAX_SERVICES_IN_MODAL:]

    edited_services = []
    for idx, svc in enumerate(shown_services):
        number = (values.get(f"rto_num__{idx}", {}).get("value", {}).get("value") or "").strip()
        selected_unit = values.get(f"rto_unit__{idx}", {}).get("value", {}).get("selected_option") or {}
        unit = (selected_unit.get("value") or "").strip()

        if unit == "Immediate":
            new_rto = "Immediate"
        elif number and unit:
            # "1 Hours"/"1 Weeks" reads wrong -- singularize the unit
            # when the number is exactly 1.
            display_unit = unit[:-1] if number.strip() == "1" and unit.endswith("s") else unit
            new_rto = f"{number} {display_unit}"
        else:
            new_rto = ""

        edited = dict(svc)
        if new_rto:
            edited["rto"] = new_rto
            edited["source"] = "Edited by admin"
        edited_services.append(edited)

    rm = dict(plan.resilience_map or {})
    rm["services"] = edited_services + remainder_services
    plan.resilience_map = rm
    plan.save()

    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    if channel_id and message_ts and bot_token:
        try:
            editing_user_id = payload.get("user", {}).get("id", "")
            card = with_nav_bar_v2(build_bia_upload_card(plan.slack_team_id, editing_user_id, bot_token), "bia_upload")
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
        except SlackApiError:
            logger.exception("Couldn't refresh Upload & Analysis card after RTO edit for team %s", plan.slack_team_id)
        except Exception:
            logger.exception("Unexpected error refreshing Upload & Analysis card after RTO edit for team %s", plan.slack_team_id)
