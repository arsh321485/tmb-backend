"""Small wrapper around the one Slack Web API call this app needs so far."""

import requests
from django.conf import settings

SLACK_VIEWS_PUBLISH_URL = "https://slack.com/api/views.publish"


class SlackApiError(Exception):
    pass


def publish_home_view(slack_user_id: str, view: dict) -> None:
    """
    Pushes `view` (a Block Kit "home" view, see view_builder.py) to the
    given Slack user's App Home tab. Requires SLACK_BOT_TOKEN with the
    `views:publish` bot scope.
    """
    if not settings.SLACK_BOT_TOKEN:
        raise SlackApiError(
            "SLACK_BOT_TOKEN isn't configured -- can't publish the Home tab."
        )

    response = requests.post(
        SLACK_VIEWS_PUBLISH_URL,
        headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
        json={"user_id": slack_user_id, "view": view},
        timeout=10,
    ).json()

    if not response.get("ok"):
        raise SlackApiError(response.get("error", "unknown_error"))
