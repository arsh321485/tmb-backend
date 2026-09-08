"""
"Upload BIA" opens a real Slack modal with a native file picker
(file_input block), instead of the previous flow (post a "drop your
file in this channel" instruction, then wait for a message.im/message
event carrying it). Modeled directly on create_team_modal.py's
views.open / view_submission pattern.

Slack's file_input element uploads the file for us and hands back the
same kind of file object (id, name, url_private_download, mimetype,
...) that a dropped-in-channel message.files[] entry has, so the actual
parsing reuses plans.intake.ingest_one_file unchanged.
"""

import json
import logging

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "upload_bia_modal"


def _metadata(channel_id: str) -> str:
    return json.dumps({"channel_id": channel_id})


def _parse_metadata(view: dict) -> str:
    try:
        data = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        data = {}
    return data.get("channel_id", "")


def build_modal_view(channel_id: str) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": _metadata(channel_id),
        "title": {"type": "plain_text", "text": "Upload BIA"},
        "submit": {"type": "plain_text", "text": "Upload"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "bia_file",
                "label": {"type": "plain_text", "text": "Business Impact Analysis"},
                "element": {
                    "type": "file_input",
                    "action_id": "value",
                    "filetypes": ["pdf", "docx", "xlsx"],
                    "max_files": 1,
                },
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


def handle_submission(payload: dict, team_id: str, bot_token: str) -> None:
    """The modal's 'Upload' submit button (view_submission)."""
    from plans.intake import ingest_one_file

    from cards.nav import with_nav_bar
    from cards.render import build_bia_ready_card
    from cards.slack_client import SlackApiError, post_card_to_channel
    from cards.models import get_or_create_state

    view = payload.get("view", {})
    channel_id = _parse_metadata(view)
    slack_user_id = payload.get("user", {}).get("id", "")

    values = view.get("state", {}).get("values", {})
    files = values.get("bia_file", {}).get("value", {}).get("files") or []
    if not files or not channel_id:
        return

    plan = ingest_one_file(files[0], channel_id, slack_user_id, team_id, bot_token, post_confirmation=False)
    if plan is None:
        return  # unsupported type / download failure -- ingest_one_file already posted why

    state = get_or_create_state(team_id)
    state.awaiting_bia = False
    state.save()

    if plan.status != "parsed":
        requests.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={
                "channel": channel_id,
                "text": f":warning: *{plan.filename}* uploaded but couldn't be read ({plan.parse_error}).",
            },
            timeout=10,
        )
        return

    card = with_nav_bar(build_bia_ready_card(plan), "bia")
    try:
        post_card_to_channel(channel_id, card, bot_token)
    except SlackApiError:
        logger.exception("Failed to post BIA-ready card for team %s", team_id)
