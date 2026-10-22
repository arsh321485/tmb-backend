"""
"Schedule" -- Step 7 · Trigger. Previously this fired the drill
immediately, identically to "Trigger now", despite claiming "pick a
window". This modal actually asks for a date and time, and the drill
waits until then (exercises.drill.fire_due_scheduled_exercises, checked
every minute by the background thread in exercises/apps.py) instead of
firing on the spot.
"""

import datetime
import json
import logging

import requests

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_trigger_schedule_modal"

logger = logging.getLogger(__name__)


def build_modal_view(module: str, scenario: str, channel_id: str = "", message_ts: str = "") -> dict:
    today = datetime.date.today().isoformat()
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Schedule the test"},
        "submit": {"type": "plain_text", "text": "Schedule"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"module": module, "scenario": scenario, "channel_id": channel_id, "message_ts": message_ts}),
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{scenario}* won't fire now — it'll wait until the date and time you pick below, then run exactly like \"Trigger now\"."},
            },
            {
                "type": "input",
                "block_id": "sched_date",
                "label": {"type": "plain_text", "text": "Date"},
                "element": {"type": "datepicker", "action_id": "value", "initial_date": today, "placeholder": {"type": "plain_text", "text": "Select a date"}},
            },
            {
                "type": "input",
                "block_id": "sched_time",
                "label": {"type": "plain_text", "text": "Time"},
                "element": {"type": "timepicker", "action_id": "value", "initial_time": "09:00", "placeholder": {"type": "plain_text", "text": "Select a time"}},
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Times are in IST._"}]},
        ],
    }


def open_modal(trigger_id: str, module: str, scenario: str, channel_id: str, message_ts: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(module, scenario, channel_id, message_ts)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    from .nav_v2 import with_nav_bar_v2
    from .trigger_v2_data import build_trigger_card

    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    module = meta.get("module", "")
    scenario = meta.get("scenario", "")
    channel_id, message_ts = meta.get("channel_id", ""), meta.get("message_ts", "")

    values = payload.get("view", {}).get("state", {}).get("values", {})
    date_str = values.get("sched_date", {}).get("value", {}).get("selected_date")
    time_str = values.get("sched_time", {}).get("value", {}).get("selected_time")

    if date_str and time_str and scenario:
        from exercises.models import Exercise
        from workspaces.models import Workspace

        local_at = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        # The date/timepicker gives back a wall-clock time with no
        # timezone attached -- treating it as UTC (what was happening
        # before) meant "13:04" only actually fired at 13:04 UTC, i.e.
        # 18:34 IST, which looked like "nothing happened" for over 5
        # hours. Sir's call: this team works in IST, so convert straight
        # from IST (UTC+5:30) rather than depending on Slack's per-user
        # tz_offset (unreliable -- returned "user_not_found" for a real
        # account when tried).
        IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
        scheduled_at = local_at - IST_OFFSET

        slack_team_id = payload.get("team", {}).get("id", "")
        workspace = Workspace.objects(team_id=slack_team_id).first()
        target_channel_id = ""
        if workspace:
            target_channel_id = (workspace.privacy_bridge_channel_id if module == "Privacy" else workspace.ir_war_room_channel_id) or ""

        exercise = Exercise(
            scenario_name=scenario,
            module=module,
            trigger_type="sched",
            status="scheduled",
            scheduled_at=scheduled_at,
            started_by_slack_user_id=payload.get("user", {}).get("id", ""),
            slack_team_id=slack_team_id,
            slack_channel_id=target_channel_id,
        )
        exercise.save()

        if channel_id and message_ts and bot_token:
            card = build_trigger_card(module, scenario, "sched")
            card["blocks"].insert(
                1,
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f":calendar: *Scheduled for {local_at.strftime('%d %b %Y, %H:%M')} IST* — it'll fire automatically, no further action needed."}],
                },
            )
            resp_json = requests.post(
                f"{SLACK_API_BASE}/chat.update",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel_id, "ts": message_ts, **with_nav_bar_v2(card, "trigger")},
                timeout=10,
            ).json()
            if not resp_json.get("ok"):
                logger.warning("chat.update failed in trigger_schedule_modal_v2: %s", resp_json)
