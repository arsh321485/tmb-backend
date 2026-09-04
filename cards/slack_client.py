"""Posts a loaded card (see loader.py) into Slack -- channel message or App Home."""

import requests

SLACK_API_BASE = "https://slack.com/api"


class SlackApiError(Exception):
    pass


def _call(method: str, bot_token: str, **payload) -> dict:
    if not bot_token:
        raise SlackApiError("No bot token for this workspace -- is it installed?")

    response = requests.post(
        f"{SLACK_API_BASE}/{method}",
        headers={"Authorization": f"Bearer {bot_token}"},
        json=payload,
        timeout=10,
    ).json()

    if not response.get("ok"):
        raise SlackApiError(response.get("error", "unknown_error"))
    return response


def post_card_to_channel(channel_id: str, card: dict, bot_token: str) -> dict:
    """
    card is a loaded chat.postMessage-shaped dict (has "blocks", optionally
    "text" as a fallback/notification string). Its own "channel" key (a
    placeholder channel *name* like "#ir-war-room" in the prototype) is
    ignored in favor of the real channel_id the caller resolved.
    """
    payload = dict(card)
    payload["channel"] = channel_id
    payload.setdefault("text", "TestMyPlan")  # Slack requires a fallback text
    return _call("chat.postMessage", bot_token, **payload)


def post_card_to_user_dm(slack_user_id: str, card: dict, bot_token: str) -> dict:
    """Same as post_card_to_channel, but to a user's DM (e.g. role assignment cards)."""
    return post_card_to_channel(slack_user_id, card, bot_token)


def publish_home_card(slack_user_id: str, card: dict, bot_token: str) -> dict:
    """card is a views.publish-shaped dict: {"type": "home", "blocks": [...]}."""
    return _call("views.publish", bot_token, user_id=slack_user_id, view=card)
