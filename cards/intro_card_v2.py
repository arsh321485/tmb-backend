"""
First-contact DM for anyone new in the Slack workspace, sent from Slack's
own "team_join" event -- fires the moment someone accepts the invite link,
before any admin has had a chance to assign them a role in Configure
Teams. General orientation only (sir's call): explains what TestMyPlan is
and how a drill will reach them, with no role/team specifics, since that
data doesn't exist yet at join time. Once an admin actually assigns them
to a team, they get the existing real Welcome -> Role -> Acknowledge card
(role_welcome_v2.py) same as today -- this card never claims to be that.
"""

import logging

from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)


def build_intro_card(recipient_name: str, org_name: str) -> dict:
    """Rendered as a real image (sir's "Welcome to TestMyPlan" design),
    same template-code approach as the other cards -- the design itself
    has no name/org text in it (the 3 feature boxes and the layout are
    identical for everyone), so recipient_name/org_name only affect the
    cache key, not anything actually drawn."""
    from django.conf import settings

    from .intro_card_image import get_intro_card_image_url

    image_url = get_intro_card_image_url(settings.BACKEND_URL, recipient_name, org_name)
    return {"blocks": [{"type": "image", "image_url": image_url, "alt_text": "Welcome to TestMyPlan"}]}


def send_intro_dm(recipient_slack_user_id: str, recipient_name: str, org_name: str, bot_token: str) -> None:
    """No-op if there's no bot token -- not fatal either way."""
    if not (recipient_slack_user_id and bot_token):
        return
    try:
        opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
        dm_channel_id = opened["channel"]["id"]
        card = build_intro_card(recipient_name, org_name)
        _call(
            "chat.postMessage",
            bot_token,
            channel=dm_channel_id,
            text="Welcome to TestMyPlan!",
            **card,
        )
    except SlackApiError:
        logger.exception("Failed to send intro DM to %s", recipient_slack_user_id)
