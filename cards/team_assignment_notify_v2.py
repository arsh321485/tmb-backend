"""
Real DM delivery when someone is assigned to a response team on the
Teams card (Step 4) -- previously nothing was sent at all; the assigned
person only found out by opening the Slack card themselves. Matches the
"PREVIEW -- DM CARD SENT TO MEMBER" mockup: team, role, who's assigned,
backup, and the already-auto-mapped responsibility/action/test phase.

Sends to BOTH the primary and the backup -- each gets their own DM, worded
for their own position (the primary owns the action; the backup is told
they're the stand-in and would run the exact same steps if called on).
"""

import logging

from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)


def _name(by_code: dict, slack_user_id: str) -> str:
    return by_code.get(slack_user_id, {}).get("n", slack_user_id)


def _send_one(
    recipient_slack_user_id: str,
    team_name: str,
    role: str,
    other_name: str,
    other_label: str,
    is_backup: bool,
    responsibility: dict | None,
    bot_token: str,
) -> None:
    opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
    dm_channel_id = opened["channel"]["id"]

    headline = f":shield: *You're the backup for a response team*\n{team_name}" if is_backup else f":shield: *You're on a response team*\n{team_name}"

    fields = [
        {"type": "mrkdwn", "text": f"*Team*\n{team_name}"},
        {"type": "mrkdwn", "text": f"*Role*\n{role}"},
    ]
    if other_name:
        fields.append({"type": "mrkdwn", "text": f"*{other_label}*\n{other_name}"})

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
        {"type": "section", "fields": fields},
    ]

    if responsibility:
        note = "If the primary can't respond, this is what you'd step in and do:" if is_backup else None
        if note:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Responsibility*\n{responsibility.get('text', '')}"},
                    {"type": "mrkdwn", "text": f"*Action*\n{responsibility.get('action', '')}: {responsibility.get('detail', '')}"},
                    {"type": "mrkdwn", "text": f"*Test phase*\n{responsibility.get('phase', '')}"},
                ],
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Nothing to install and nothing to read in advance. When a test fires you'll get one card at a time, right here.",
                }
            ],
        }
    )

    _call(
        "chat.postMessage",
        bot_token,
        channel=dm_channel_id,
        text=f"You're the backup for {team_name} ({role})." if is_backup else f"You've been added to {team_name} as {role}.",
        blocks=blocks,
    )


def send_team_assignment_dm(
    team_id: str,
    team_name: str,
    role: str,
    primary_slack_user_id: str,
    backup_slack_user_id: str,
    responsibility: dict | None,
    by_code: dict,
    bot_token: str,
) -> None:
    """No-op if there's no bot token -- not fatal either way."""
    if not (team_id and bot_token):
        return

    primary_name = _name(by_code, primary_slack_user_id) if primary_slack_user_id else ""
    backup_name = _name(by_code, backup_slack_user_id) if backup_slack_user_id else ""

    if primary_slack_user_id:
        try:
            _send_one(primary_slack_user_id, team_name, role, backup_name, "Backup", False, responsibility, bot_token)
        except SlackApiError:
            logger.exception("Failed to DM %s about %s team assignment for team %s", primary_slack_user_id, team_name, team_id)

    if backup_slack_user_id and backup_slack_user_id != primary_slack_user_id:
        try:
            _send_one(backup_slack_user_id, team_name, role, primary_name, "Primary", True, responsibility, bot_token)
        except SlackApiError:
            logger.exception("Failed to DM %s about %s backup assignment for team %s", backup_slack_user_id, team_name, team_id)
