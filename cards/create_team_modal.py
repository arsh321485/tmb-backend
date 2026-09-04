"""
The "Create a team" button opens a real Slack modal (a popup form) --
unlike regular channel cards, modals support proper form inputs: a text
field, a dropdown, and a real member picker (multi_users_select, which
searches the actual workspace directory, better than the prototype's
4 mock avatars).
"""

import requests

from .models import CustomTeam, get_or_create_state

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "create_team_modal"

MODULE_OPTIONS = ["Cybersecurity", "Privacy", "Business Continuity", "ESG", "Crisis Comms"]


def build_modal_view(channel_id: str) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        # Carries the channel to confirm in, through to the submission handler.
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Create a team"},
        "submit": {"type": "plain_text", "text": "Create team"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "team_name",
                "label": {"type": "plain_text", "text": "Team name"},
                "element": {"type": "plain_text_input", "action_id": "value"},
            },
            {
                "type": "input",
                "block_id": "module",
                "label": {"type": "plain_text", "text": "Module"},
                "optional": True,
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [
                        {"text": {"type": "plain_text", "text": m}, "value": m}
                        for m in MODULE_OPTIONS
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "members",
                "label": {"type": "plain_text", "text": "Members"},
                "optional": True,
                "element": {"type": "multi_users_select", "action_id": "value"},
            },
        ],
    }


def open_modal(trigger_id: str, channel_id: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(channel_id)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    """Called when the modal is submitted (view_submission, not block_actions)."""
    view = payload.get("view", {})
    team_id = payload.get("team", {}).get("id", "")
    channel_id = view.get("private_metadata", "")

    values = view.get("state", {}).get("values", {})
    name = values.get("team_name", {}).get("value", {}).get("value", "").strip()
    module_option = values.get("module", {}).get("value", {}).get("selected_option")
    module = module_option["value"] if module_option else None
    member_ids = [
        u for u in values.get("members", {}).get("value", {}).get("selected_users", [])
    ]

    if not name:
        return

    state = get_or_create_state(team_id)
    state.custom_teams.append(
        CustomTeam(name=name, module=module, member_slack_user_ids=member_ids)
    )
    state.save()

    if channel_id:
        member_note = f" with {len(member_ids)} member(s)" if member_ids else ""
        requests.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={
                "channel": channel_id,
                "text": f":white_check_mark: Team *{name}* created{member_note}.",
            },
            timeout=10,
        )
