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
    org_bit = f" at {org_name}" if org_name else ""
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":wave: Welcome to TestMyPlan!", "emoji": True}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi {recipient_name}, you've been added to TestMyPlan{org_bit} -- TestMyPlan helps your organization improve cybersecurity incident preparedness through realistic, scenario-based drills.",
                },
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": "*What you'll get here*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":bell: *Drill Notifications* -- know the moment a drill starts\n"
                        ":clipboard: *Task & Decision Cards* -- incident updates and decisions, right in this DM\n"
                        ":dart: *Respond in Slack* -- submit your decisions directly through the cards\n\n"
                        ":white_check_mark: *You're all set* -- no action needed right now. We'll message you here when a drill begins."
                    ),
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":lock: This is a simulated drill environment -- follow your org's guidelines."}],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": "*TestMyPlan -- Be Prepared. Respond Better.*"}},
        ]
    }


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
