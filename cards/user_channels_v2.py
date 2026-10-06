"""
Creates the 3 participant-side exercise channels (user_screen design):

  #ir-war-room       -- where the live drill actually happens
  #privacy-bridge     -- side channel for legal/privacy during an exercise
  testmyplan-general   -- workspace-wide announcements (named "testmyplan-general",
                          not "general" -- Slack already reserves that name
                          for every workspace's own built-in channel)

No cards are posted into these yet -- just the channels themselves, cached
on the Workspace record the same way as new_design_preview_channel_id so
we never need conversations.list to re-find them later.
"""

import logging

from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)

# (field name on Workspace, channel name, private?)
USER_CHANNELS = [
    ("ir_war_room_channel_id", "ir-war-room", True),
    ("privacy_bridge_channel_id", "privacy-bridge", True),
    ("general_channel_id", "testmyplan-general", False),
]


def ensure_user_channels(team_id: str, bot_token: str) -> dict:
    """
    Creates any of the 3 channels that don't exist yet for this workspace.
    Returns {"ir_war_room_channel_id": ..., "privacy_bridge_channel_id": ...,
    "general_channel_id": ...}.
    """
    from workspaces.models import Workspace

    workspace = Workspace.objects(team_id=team_id).first()
    result = {}

    for field, name, is_private in USER_CHANNELS:
        existing = getattr(workspace, field, None) if workspace else None
        if existing:
            result[field] = existing
            continue

        try:
            created = _call("conversations.create", bot_token, name=name, is_private=is_private)
            channel_id = created["channel"]["id"]
        except SlackApiError as exc:
            if str(exc) != "name_taken":
                logger.exception("Failed to create %s for team %s", name, team_id)
                continue
            # Already exists (e.g. from a previous run) but we don't have
            # its id cached -- nothing more we can do without channels:read.
            logger.warning("Channel %s already exists for team %s but id not cached", name, team_id)
            continue

        result[field] = channel_id
        if workspace:
            setattr(workspace, field, channel_id)

    if workspace:
        workspace.save()

    return result
