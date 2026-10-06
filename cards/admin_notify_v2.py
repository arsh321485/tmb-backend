"""
Real DM delivery when someone is assigned as a module admin -- the
"Notified via DM" label on the Module Admins card used to just be text;
nothing was actually sent. This sends a real Slack DM.
"""

import logging

from .admins_v2_data import MODULE_ADMINS
from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)


def _module_label(module_id: str) -> str:
    for mod in MODULE_ADMINS:
        if mod["id"] == module_id:
            return mod["m"]
    return module_id


def send_admin_assigned_dm(team_id: str, module_id: str, target_slack_user_id: str, bot_token: str) -> None:
    """No-op for self-assignment -- no need to DM yourself."""
    if not (team_id and module_id and target_slack_user_id and bot_token):
        return

    try:
        opened = _call("conversations.open", bot_token, users=target_slack_user_id)
        dm_channel_id = opened["channel"]["id"]

        from workspaces.models import Workspace

        workspace = Workspace.objects(team_id=team_id).first()
        org_name = (workspace.team_name if workspace else "") or "your organization"
        module_label = _module_label(module_id)
        _call(
            "chat.postMessage",
            bot_token,
            channel=dm_channel_id,
            text=(
                f":shield: You've been made *{module_label} admin* for *{org_name}* in TestMyPlan.\n"
                f"You now own setting up and running readiness tests for that module — head to "
                f"#testmyplan-command-center any time to review or change it."
            ),
        )
    except SlackApiError:
        logger.exception("Failed to DM %s about %s admin assignment for team %s", target_slack_user_id, module_id, team_id)
