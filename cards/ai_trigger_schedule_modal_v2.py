"""
"Schedule" for an approved AI-generated scenario (cards/ai_drill_v2.py) --
asks for a date and time, same idea as cards/trigger_schedule_modal_v2.py
(the real drills' version) but a separate modal/callback_id so nothing
there needs to change.
"""

import datetime
import json
import logging

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_ai_trigger_schedule_modal"


def build_modal_view(scenario_id: str, channel_id: str = "") -> dict:
    now = datetime.datetime.utcnow()
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"scenario_id": scenario_id, "channel_id": channel_id}),
        "title": {"type": "plain_text", "text": "Schedule this scenario"},
        "submit": {"type": "plain_text", "text": "Schedule"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "date_block",
                "label": {"type": "plain_text", "text": "Date"},
                "element": {"type": "datepicker", "action_id": "value", "initial_date": now.strftime("%Y-%m-%d")},
            },
            {
                "type": "input",
                "block_id": "time_block",
                "label": {"type": "plain_text", "text": "Time (UTC)"},
                "element": {"type": "timepicker", "action_id": "value", "initial_time": "09:00"},
            },
        ],
    }


def open_modal(trigger_id: str, scenario_id: str, channel_id: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(scenario_id, channel_id)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    from . import ai_drill_v2
    from .models_v2 import GeneratedScenario

    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        return
    scenario_id = meta.get("scenario_id", "")
    channel_id = meta.get("channel_id", "")
    scenario = GeneratedScenario.objects(id=scenario_id).first() if scenario_id else None
    if not scenario:
        return

    values = view.get("state", {}).get("values", {})
    date_str = values.get("date_block", {}).get("value", {}).get("selected_date")
    time_str = values.get("time_block", {}).get("value", {}).get("selected_time")
    if not (date_str and time_str):
        return

    scheduled_at = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    current_user_id = payload.get("user", {}).get("id", "")
    ai_drill_v2.start_run(scenario, "scheduled", current_user_id, bot_token, scheduled_at=scheduled_at, origin_channel_id=channel_id)
