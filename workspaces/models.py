import datetime

import mongoengine as me


class Workspace(me.Document):
    """
    One client's Slack workspace that has installed the TestMyPlan bot.
    Each workspace gets its own bot token -- Securitlab's actions must
    never use another client's token, and vice versa. Keyed by Slack's
    team id, which is unique per workspace.
    """

    team_id = me.StringField(required=True, unique=True)
    team_name = me.StringField(required=False)

    bot_token = me.StringField(required=True)  # xoxb-... for this workspace
    bot_user_id = me.StringField(required=False)

    installed_by_slack_user_id = me.StringField(required=False)
    installed_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "workspaces"}


def get_bot_token(team_id: str) -> str | None:
    """Returns the bot token for a given Slack team, or None if not installed."""
    if not team_id:
        return None
    workspace = Workspace.objects(team_id=team_id).first()
    return workspace.bot_token if workspace else None
