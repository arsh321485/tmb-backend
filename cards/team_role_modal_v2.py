"""
Any "+ Add a ___ not listed…" option on the new-design preview's Teams
step (role, responsibility, or the exact action) opens this same modal
-- a real text input, since Slack buttons/selects can't take free text.
Submitting brings you right back to the same message with that typed
text pre-filled in the right spot. Kept separate from anything else in
the app -- this only ever touches the #testmyplan-command-center preview.
"""

import json
import logging

import requests

from .nav_v2 import with_nav_bar_v2
from .teams_v2_data import build_teams_card

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_team_role_modal"

# What we're filling in and its human label for the modal's input.
FIELD_LABELS = {"role": "Role name", "resp": "Responsibility", "detail": "The exact action"}


def _metadata(field: str, team_id: str, channel_id: str, message_ts: str, teams: dict, resp: dict, add: dict, map_state: dict) -> str:
    return json.dumps(
        {
            "field": field,
            "team_id": team_id,
            "channel_id": channel_id,
            "message_ts": message_ts,
            "teams": teams,
            "resp": resp,
            "add": add,
            "map": map_state,
        }
    )


def build_modal_view(field: str, **kwargs) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": _metadata(field, **kwargs),
        "title": {"type": "plain_text", "text": "Add your own"},
        "submit": {"type": "plain_text", "text": "Add"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "custom_text",
                "label": {"type": "plain_text", "text": FIELD_LABELS.get(field, "Text")},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
        ],
    }


def open_modal(trigger_id: str, field: str, team_id: str, channel_id: str, message_ts: str, teams: dict, resp: dict, add: dict, map_state: dict, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={
            "trigger_id": trigger_id,
            "view": build_modal_view(field, team_id=team_id, channel_id=channel_id, message_ts=message_ts, teams=teams, resp=resp, add=add, map_state=map_state),
        },
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        return

    field = meta.get("field", "")
    team_id = meta.get("team_id", "")
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    teams = meta.get("teams", {})
    resp = meta.get("resp", {})
    add = meta.get("add")
    map_state = meta.get("map")
    if not (field and team_id and channel_id and message_ts):
        return

    values = view.get("state", {}).get("values", {})
    text = values.get("custom_text", {}).get("value", {}).get("value", "").strip()
    if not text:
        return

    if field == "role":
        add = {"team_id": team_id, "role": text, "primary": [], "backup": []}
    elif field == "resp":
        map_state = {"team_id": team_id, "text": text, "who": None, "action": None, "detail": None, "phase": "Containment"}
    elif field == "detail":
        map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "phase": "Containment"}
        map_state["detail"] = text

    state = {"teams": teams, "resp": resp, "add": add, "map": map_state}
    card = with_nav_bar_v2(build_teams_card(state), "teams")

    resp_json = requests.post(
        f"{SLACK_API_BASE}/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    ).json()
    if not resp_json.get("ok"):
        # requests doesn't raise on a Slack-level rejection (HTTP 200
        # with ok:false) -- confirmed live: an invalid_blocks error here
        # failed completely silently and just showed as "trouble
        # connecting" in the modal, with nothing in our own logs.
        logger.warning("chat.update failed in team_role_modal_v2: %s", resp_json)
