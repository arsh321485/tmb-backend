"""
Real DM delivery when someone is assigned to a response team on the
Teams card (Step 4) -- previously nothing was sent at all; the assigned
person only found out by opening the Slack card themselves.

Now sends the real Welcome -> Role -> Acknowledge flow (role_welcome_v2.py,
built from userflow/assignmentcard.html) instead of one flat DM: a short
welcome, then (on click) the full role assignment, then an explicit
timestamped acknowledgement before they're counted as ready.

Sends to BOTH the primary and the backup -- each gets their own DM flow,
worded for their own position (the primary owns the action; the backup
is told they're the stand-in and would run the exact same steps if
called on).
"""

import logging

logger = logging.getLogger(__name__)


def send_team_assignment_dm(
    team_id: str,
    team_name: str,
    role: str,
    primary_slack_user_id: str,
    backup_slack_user_id: str,
    responsibility: dict | None,
    by_code: dict,
    bot_token: str,
    catalog_team_id: str = "",
) -> None:
    """No-op if there's no bot token -- not fatal either way."""
    if not (team_id and bot_token):
        return

    from . import role_welcome_v2

    if primary_slack_user_id:
        role_welcome_v2.send_welcome_dm(primary_slack_user_id, catalog_team_id or team_id, team_name, role, False, bot_token)

    if backup_slack_user_id and backup_slack_user_id != primary_slack_user_id:
        role_welcome_v2.send_welcome_dm(backup_slack_user_id, catalog_team_id or team_id, team_name, role, True, bot_token)
