"""
"+ Add service" on Upload & Analysis -- lets the admin add a real
service/process the uploaded BIA/BCP missed entirely, instead of only
being able to correct an RTO the AI already extracted (that's
edit_rtos_modal_v2.py's job). Same number+unit RTO input as that modal,
same reasoning: a free-typed unit is what caused the original RTO sort
bug (plans/threat_ranking.py's _rto_to_hours), so the unit stays a
dropdown here too.
"""

import json
import logging

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_add_service_modal"

CATEGORY_OPTIONS = ["Service", "Technology", "Application"]
UNIT_OPTIONS = ["Minutes", "Hours", "Days", "Weeks", "Months"]


def build_modal_view(plan, channel_id: str = "", message_ts: str = "") -> dict:
    unit_options = [{"text": {"type": "plain_text", "text": "Immediate"}, "value": "Immediate"}] + [
        {"text": {"type": "plain_text", "text": u}, "value": u} for u in UNIT_OPTIONS
    ]
    category_options = [{"text": {"type": "plain_text", "text": c}, "value": c} for c in CATEGORY_OPTIONS]

    blocks = [
        {"type": "input", "block_id": "name", "label": {"type": "plain_text", "text": "Service / process name"},
         "element": {"type": "plain_text_input", "action_id": "value", "placeholder": {"type": "plain_text", "text": "e.g. Core Banking Platform"}}},
        {"type": "input", "block_id": "category", "label": {"type": "plain_text", "text": "Category"},
         "element": {"type": "static_select", "action_id": "value", "options": category_options, "initial_option": category_options[0]}},
        {"type": "input", "block_id": "rto_num", "optional": True, "label": {"type": "plain_text", "text": "RTO — number"},
         "element": {"type": "plain_text_input", "action_id": "value", "placeholder": {"type": "plain_text", "text": "e.g. 4"}}},
        {"type": "input", "block_id": "rto_unit", "optional": True, "label": {"type": "plain_text", "text": "RTO — unit"},
         "element": {"type": "static_select", "action_id": "value", "placeholder": {"type": "plain_text", "text": "Unit"}, "options": unit_options}},
    ]

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"plan_id": str(plan.id), "channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Add service"},
        "submit": {"type": "plain_text", "text": "Add"},
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
    """view_submission here runs fully in the background, after Slack's
    already been ACKed (cards/views.py) -- a response_action error sent
    back from this function would never actually reach Slack, so the
    "name" input block is a required (non-optional) block instead,
    which Slack's own client blocks an empty submission against before
    it's even sent here. Same reasoning other v2 modals in this
    codebase already rely on for required fields."""
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
    name = (values.get("name", {}).get("value", {}).get("value") or "").strip()
    if not name:
        return

    category_sel = values.get("category", {}).get("value", {}).get("selected_option") or {}
    category = category_sel.get("value") or "Service"

    number = (values.get("rto_num", {}).get("value", {}).get("value") or "").strip()
    unit_sel = values.get("rto_unit", {}).get("value", {}).get("selected_option") or {}
    unit = (unit_sel.get("value") or "").strip()

    if unit == "Immediate":
        rto = "Immediate"
    elif number and unit:
        display_unit = unit[:-1] if number == "1" and unit.endswith("s") else unit
        rto = f"{number} {display_unit}"
    else:
        rto = ""

    rm = dict(plan.resilience_map or {})
    services = list(rm.get("services") or [])
    services.append(
        {
            "name": name,
            "category": category,
            "rto": rto,
            "source": "Added by admin",
            "dependencies": [],
            "supporting_systems": [],
        }
    )
    rm["services"] = services
    plan.resilience_map = rm
    plan.save()

    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    if channel_id and message_ts and bot_token:
        try:
            adding_user_id = payload.get("user", {}).get("id", "")
            card = with_nav_bar_v2(build_bia_upload_card(plan.slack_team_id, adding_user_id, bot_token), "bia_upload")
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
        except SlackApiError:
            logger.exception("Couldn't refresh Upload & Analysis card after adding a service for team %s", plan.slack_team_id)
        except Exception:
            logger.exception("Unexpected error refreshing Upload & Analysis card after adding a service for team %s", plan.slack_team_id)
