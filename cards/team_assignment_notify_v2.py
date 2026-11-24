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

    from . import persistence_v2, role_welcome_v2
    from .models_v2 import Team, TeamMember

    resolved_catalog_team_id = catalog_team_id or team_id

    # Re-uses the SAME Welcome message for a person already assigned to
    # this exact role, instead of posting a brand new one every time
    # Configure Teams is saved -- confirmed live: re-assigning during
    # testing left old Welcome DMs stacked, untouched, in the channel.
    team_doc = Team.objects(team_id=team_id, slug=resolved_catalog_team_id).first()
    member = TeamMember.objects(team=team_doc, role=role).first() if team_doc else None

    if primary_slack_user_id:
        existing = (member.welcome_dm_location or {}).get(primary_slack_user_id) if member else None
        result = role_welcome_v2.send_welcome_dm(primary_slack_user_id, resolved_catalog_team_id, team_name, role, False, bot_token, existing)
        persistence_v2.record_dm_status(team_id, resolved_catalog_team_id, role, primary_slack_user_id, "sent" if result["ok"] else "failed")
        if result["ok"] and member:
            member.welcome_dm_location[primary_slack_user_id] = {"channel_id": result["channel_id"], "message_ts": result["message_ts"]}
            member.save()

    if backup_slack_user_id and backup_slack_user_id != primary_slack_user_id:
        existing = (member.welcome_dm_location or {}).get(backup_slack_user_id) if member else None
        result = role_welcome_v2.send_welcome_dm(backup_slack_user_id, resolved_catalog_team_id, team_name, role, True, bot_token, existing)
        persistence_v2.record_dm_status(team_id, resolved_catalog_team_id, role, backup_slack_user_id, "sent" if result["ok"] else "failed")
        if result["ok"] and member:
            member.welcome_dm_location[backup_slack_user_id] = {"channel_id": result["channel_id"], "message_ts": result["message_ts"]}
            member.save()
