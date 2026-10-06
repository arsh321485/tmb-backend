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

    # Cached so re-posting an update to this channel never needs
    # conversations.list -- several already-installed workspaces predate
    # the channels:read scope and can't call that API at all (confirmed
    # live: "missing_scope" on every one of them). Remembering the ID the
    # moment we create it sidesteps needing that permission ever again.
    new_design_preview_channel_id = me.StringField(required=False)

    # The 3 participant-side exercise channels (user_screen design):
    # war-room (the live drill), privacy-bridge (legal/privacy side
    # channel), and general (workspace-wide announcements). Cached the
    # same way as new_design_preview_channel_id, same reason.
    ir_war_room_channel_id = me.StringField(required=False)
    privacy_bridge_channel_id = me.StringField(required=False)
    general_channel_id = me.StringField(required=False)

    # Guards against posting the Welcome card (and creating channels)
    # more than once for the same workspace -- confirmed live: a slow
    # request (several sequential Slack API calls) plus a retried
    # browser/Slack request caused the same onboarding to run 2-3 times,
    # posting duplicate Welcome cards. Claimed atomically (see
    # workspaces.models.claim_onboarding) so even two near-simultaneous
    # calls only let one through.
    onboarding_completed = me.BooleanField(default=False)

    meta = {"collection": "workspaces"}


def claim_onboarding(team_id: str) -> bool:
    """
    Atomically marks this workspace's onboarding as done, returning True
    only the FIRST time this is ever called for a given team_id. Any
    later or concurrent call (a retried request, a slow duplicate) gets
    False and must not post the Welcome card or create channels again.
    """
    updated = Workspace.objects(team_id=team_id, onboarding_completed__ne=True).modify(
        set__onboarding_completed=True
    )
    return updated is not None


def get_bot_token(team_id: str) -> str | None:
    """Returns the bot token for a given Slack team, or None if not installed."""
    if not team_id:
        return None
    workspace = Workspace.objects(team_id=team_id).first()
    return workspace.bot_token if workspace else None
