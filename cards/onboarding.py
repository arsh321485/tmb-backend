"""
What happens right after a workspace installs TestMyPlan: create the
`#testmyplan-command-center` channel (per the card design's assumption
that setup/reporting cards live there) and post the Welcome card into it.
"""

import logging

from .loader import load_card
from .slack_client import SlackApiError, _call, post_card_to_channel

logger = logging.getLogger(__name__)

COMMAND_CENTER_CHANNEL_NAME = "testmyplan-command-center"


def ensure_command_center_channel(bot_token: str) -> str:
    """Creates the command center channel, or finds it if it already exists. Returns its id."""
    try:
        created = _call(
            "conversations.create", bot_token, name=COMMAND_CENTER_CHANNEL_NAME, is_private=False
        )
        return created["channel"]["id"]
    except SlackApiError as exc:
        if str(exc) != "name_taken":
            raise
        return _find_existing_channel(bot_token)


def _find_existing_channel(bot_token: str) -> str:
    listing = _call("conversations.list", bot_token, exclude_archived=True, limit=200)
    for channel in listing.get("channels", []):
        if channel.get("name") == COMMAND_CENTER_CHANNEL_NAME:
            return channel["id"]
    raise SlackApiError("command_center_channel_not_found")


def send_welcome(installer_slack_user_id: str, org_name: str, person_name: str, bot_token: str) -> None:
    """
    Creates/finds the command center channel, invites the installer, and
    posts the Welcome card (01-welcome.json). Called right after a
    successful /api/auth/slack/callback/ install.
    """
    try:
        channel_id = ensure_command_center_channel(bot_token)

        try:
            _call("conversations.invite", bot_token, channel=channel_id, users=installer_slack_user_id)
        except SlackApiError:
            pass  # already a member, or can't invite -- not fatal

        card = load_card("01-welcome.json", org_name=org_name, person_name=person_name)
        post_card_to_channel(channel_id, card, bot_token)
    except SlackApiError:
        logger.exception("Failed to send welcome card for installer %s", installer_slack_user_id)
