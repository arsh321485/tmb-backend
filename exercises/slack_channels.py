"""
Auto-provisioned exercise channels (A6) + the exercise safety banner (K1).

Creates a dedicated Slack channel per drill, invites the person who started
it, and posts a persistent banner marking every message in it as simulated
-- so drill chatter never gets mistaken for a real incident. Archives the
channel again once the exercise ends.
"""

import re
import time

import requests
from django.conf import settings

SLACK_API_BASE = "https://slack.com/api"

EXERCISE_BANNER = (
    ":rotating_light: *THIS IS A SIMULATED EXERCISE* :rotating_light:\n"
    "Nothing in this channel is a real incident. All messages here are "
    "part of a TestMyPlan drill."
)


class SlackApiError(Exception):
    pass


def _call(method: str, **payload) -> dict:
    if not settings.SLACK_BOT_TOKEN:
        raise SlackApiError("SLACK_BOT_TOKEN isn't configured.")

    response = requests.post(
        f"{SLACK_API_BASE}/{method}",
        headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
        json=payload,
        timeout=10,
    ).json()

    if not response.get("ok"):
        raise SlackApiError(response.get("error", "unknown_error"))
    return response


def _channel_name_for(scenario_name: str) -> str:
    """Slack channel names: lowercase, no spaces, letters/numbers/hyphens only."""
    slug = re.sub(r"[^a-z0-9]+", "-", scenario_name.lower()).strip("-")
    return f"exercise-{slug}-{int(time.time())}"[:80]


def provision_exercise_channel(scenario_name: str, inviter_slack_user_id: str = "") -> dict:
    """
    Creates the channel, invites the person who ran /testmyplan run, and
    posts the exercise safety banner. Returns {"id": ..., "name": ...}.
    """
    channel_name = _channel_name_for(scenario_name)

    created = _call("conversations.create", name=channel_name, is_private=False)
    channel_id = created["channel"]["id"]

    if inviter_slack_user_id:
        try:
            _call("conversations.invite", channel=channel_id, users=inviter_slack_user_id)
        except SlackApiError:
            # Not fatal -- the channel still exists, they can be added manually.
            pass

    _call("chat.postMessage", channel=channel_id, text=EXERCISE_BANNER)

    return {"id": channel_id, "name": created["channel"]["name"]}


def archive_exercise_channel(channel_id: str) -> None:
    _call(
        "chat.postMessage",
        channel=channel_id,
        text=":checkered_flag: Exercise ended. This channel is now archived.",
    )
    _call("conversations.archive", channel=channel_id)
