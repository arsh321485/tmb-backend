"""
Real Slack version of the Welcome -> Role -> Acknowledge DM flow
(userflow (2)/userflow/assignmentcard.html). Sent to someone the moment
they're assigned a role on Configure Teams (team_assignment_notify_v2),
replacing the old single flat DM with three steps: a short welcome, the
full role assignment (team, role, primary/backup, responsibility, test
phase, priority), and an explicit timestamped acknowledgement before
they're counted as "ready" -- previously a drill just assumed everyone
was briefed; now there's a real logged confirmation.

Each card replaces the same message in place (chat.update), same as the
mockup's single-feed click-through -- not three separate DMs.
"""

import logging

from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)


def _value(catalog_team_id: str, role: str, is_backup: bool) -> str:
    return f"{catalog_team_id}|{role}|{'1' if is_backup else '0'}"


def parse_value(value: str) -> tuple[str, str, bool]:
    catalog_team_id, role, backup_flag = value.split("|", 2)
    return catalog_team_id, role, backup_flag == "1"


def build_welcome_card(recipient_name: str, catalog_team_id: str, team_name: str, role: str, is_backup: bool) -> dict:
    badge = ":large_orange_circle: *BACKUP*" if is_backup else ":large_green_circle: *RESPONSE TEAM*"
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f":wave: Welcome, {recipient_name}!", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{badge}  ·  {team_name}"}]},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "This DM is where your drill runs — every step arrives as one card at a time, nothing to install."},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": "*How it works*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":one: *Review* your assigned role and responsibilities\n"
                        ":two: *Read* each task card as it arrives\n"
                        ":three: *Respond* directly in the card — your answer is logged and timed\n"
                        ":four: *Complete* all tasks before the exercise ends"
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "→ View my role & responsibilities", "emoji": True},
                        "action_id": "v2_role_view",
                        "value": _value(catalog_team_id, role, is_backup),
                        "style": "primary",
                    }
                ],
            },
        ]
    }


def build_role_card(catalog_team_id: str, team_name: str, role: str, primary_name: str, backup_name: str, is_backup: bool, responsibility: dict | None, value: str) -> dict:
    fields = [
        {"type": "mrkdwn", "text": f"*Team*\n{team_name}"},
        {"type": "mrkdwn", "text": f"*Role*\n{role}"},
    ]
    if is_backup:
        fields.append({"type": "mrkdwn", "text": f"*Primary*\n{primary_name or '—'}"})
    else:
        fields.append({"type": "mrkdwn", "text": f"*Backup*\n{backup_name or '—'}"})

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": ":clipboard: *Your role assignment*"}},
        {"type": "section", "fields": fields},
    ]

    if is_backup:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "If the primary can't respond, these are the activities you'd step in and run:"}]})

    # Real multi-row activity list for this role (sir's IR Team Catalog
    # spreadsheet, Roles sheet) -- replaces the mockup's example table
    # with the real activities this role actually owns, across every
    # phase, not just a single auto-mapped action.
    from .role_activities_v2 import activities_for_role

    activities = activities_for_role(catalog_team_id, role)
    if activities:
        # Role Responsibilities column from the same spreadsheet row --
        # one text per role (repeats across that role's activity rows),
        # shown once here rather than once per activity.
        real_responsibility = activities[0].get("responsibility", "")
        if real_responsibility:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Responsibility*\n{real_responsibility}"}})

        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Your IR Activities*"}]})
        lines = [f"• `{a['activity_id']}` *{a['activity']}* — {a['phase']}" for a in activities]
        for chunk_start in range(0, len(lines), 8):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines[chunk_start:chunk_start + 8])}})
    elif responsibility:
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
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Acknowledge my role", "emoji": True},
                    "action_id": "v2_role_acknowledge",
                    "value": value,
                    "style": "primary",
                }
            ],
        }
    )
    return {"blocks": blocks}


def build_ack_card(recipient_name: str, team_name: str, role: str, value: str) -> dict:
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: *Confirm your role assignment*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"I, *{recipient_name}*, confirm that I understand my role as *{role}* on *{team_name}*. I've reviewed my responsibilities and I'm ready to respond when a test fires.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "I acknowledge — I'm ready", "emoji": True},
                        "action_id": "v2_role_ack_confirm",
                        "value": value,
                        "style": "primary",
                    }
                ],
            },
        ]
    }


def build_ack_done_card(acknowledged_at_text: str) -> dict:
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: *Acknowledged*"}},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Logged {acknowledged_at_text}. Your first task card will arrive here when the test fires."}
                ],
            },
        ]
    }


def send_welcome_dm(recipient_slack_user_id: str, catalog_team_id: str, team_name: str, role: str, is_backup: bool, bot_token: str) -> None:
    """No-op if there's no bot token -- not fatal either way."""
    if not (recipient_slack_user_id and bot_token):
        return
    try:
        opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
        dm_channel_id = opened["channel"]["id"]
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}
        recipient_name = by_code.get(recipient_slack_user_id, {}).get("n", "there")

        card = build_welcome_card(recipient_name, catalog_team_id, team_name, role, is_backup)
        _call(
            "chat.postMessage",
            bot_token,
            channel=dm_channel_id,
            text=f"You've been added to {team_name} as {role}.",
            **card,
        )
    except SlackApiError:
        logger.exception("Failed to send welcome DM to %s for %s / %s", recipient_slack_user_id, team_name, role)
