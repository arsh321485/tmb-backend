"""Small wrapper around the one Slack Web API call this app needs so far."""

import requests

SLACK_VIEWS_PUBLISH_URL = "https://slack.com/api/views.publish"


class SlackApiError(Exception):
    pass


def publish_home_view(slack_user_id: str, view: dict, bot_token: str) -> None:
    """
    Pushes `view` (a Block Kit "home" view, see view_builder.py) to the
    given Slack user's App Home tab, using that user's own workspace's bot
    token (see workspaces/models.py) -- never a different client's token.
    """
    if not bot_token:
        raise SlackApiError("No bot token for this workspace -- is it installed?")

    response = requests.post(
        SLACK_VIEWS_PUBLISH_URL,
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"user_id": slack_user_id, "view": view},
        timeout=10,
    ).json()

    if not response.get("ok"):
        raise SlackApiError(response.get("error", "unknown_error"))
