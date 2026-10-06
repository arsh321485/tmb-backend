"""
"Invite by email" on the Module Admins card -- a real modal (Full name +
email), matching the updated design. Honest limitation, same one already
confirmed live earlier in this project: our bot can't actually send a
Slack workspace invite by email (Slack blocks that for a standard bot
token). So this records who the admin INTENDS to make the admin -- the
admin still has to invite them into Slack themselves (Slack's own native
invite screen) -- and once that person is a real Slack member, the admin
can assign them for real from the "Change" option on this same card.
"""

import json

import requests

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_admin_invite_modal"


def _metadata(module_id: str, channel_id: str, message_ts: str) -> str:
    return json.dumps({"module_id": module_id, "channel_id": channel_id, "message_ts": message_ts})


def build_modal_view(module_id: str, channel_id: str, message_ts: str, module_label: str) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": _metadata(module_id, channel_id, message_ts),
        "title": {"type": "plain_text", "text": "Invite an admin"},
        "submit": {"type": "plain_text", "text": "Invite"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Who should be *{module_label} admin*? This records your invite here -- you'll still need to add them to this Slack workspace yourself (Slack's own \"Invite people\") since a bot can't do that part.",
                },
            },
            {
                "type": "input",
                "block_id": "full_name",
                "label": {"type": "plain_text", "text": "Full name"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "email",
                "label": {"type": "plain_text", "text": "Email"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
        ],
    }


def open_modal(trigger_id: str, module_id: str, channel_id: str, message_ts: str, module_label: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(module_id, channel_id, message_ts, module_label)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    from . import persistence_v2
    from .admins_v2_data import build_admins_card
    from .nav_v2 import with_nav_bar_v2
    from .slack_members_v2 import get_workspace_people

    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except (ValueError, TypeError):
        return

    module_id = meta.get("module_id", "")
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    team_id = payload.get("team", {}).get("id", "")
    current_user_id = payload.get("user", {}).get("id", "")
    if not (module_id and channel_id and message_ts and bot_token):
        return

    values = view.get("state", {}).get("values", {})
    full_name = (values.get("full_name", {}).get("value", {}).get("value") or "").strip()
    email = (values.get("email", {}).get("value", {}).get("value") or "").strip()
    if not full_name:
        return

    # Encoded as a fake "person code" so the rest of the admins card
    # machinery (built for real Slack user ids) can display it the same
    # way -- admins_v2_data.py recognizes the "invited:" prefix specially.
    invited_code = f"invited:{full_name}|{email}"
    state = persistence_v2.load_admins_state(team_id)
    state["assigned"][module_id] = invited_code
    persistence_v2.save_admins_state(team_id, state["assigned"])

    people = get_workspace_people(bot_token)
    card = with_nav_bar_v2(build_admins_card(state, people, current_user_id), "admins")
    requests.post(
        f"{SLACK_API_BASE}/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    )
