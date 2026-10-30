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


def build_plans_bia_card(org_name: str) -> dict:
    """Phase 1 (Read) -- a real card instead of a plain text line, since
    this is their actual job assignment (same weight/style as the team
    role Welcome card in role_welcome_v2.py, not a one-line FYI)."""
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":shield: You're the Plans & BIA Admin", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "You're now responsible for giving TestMyPlan the organization's real plan."}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": ":sparkles: *How it works*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":inbox_tray: *Drop* the real continuity plan (BCP, BIA or DR runbook) right here in this DM",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":mag_right: *Review* what the AI found — services, RTO / RPO / MTPD, dependencies",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":lock: *Confirm* it, resolve any gaps, and lock in the final objectives register",
                },
            },
            {"type": "divider"},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": ":page_facing_up: PDF, Word or Excel — just attach the file to a message here whenever you're ready."}]},
        ]
    }


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

        if module_id == "plans_bia":
            # Phase 1 (Read) -- their actual job is specific and
            # actionable, not just "go look at a command center" like
            # the other modules -- a real card, not a one-line text
            # message (sir's call: the plain text felt too small).
            card = build_plans_bia_card(org_name)
            _call(
                "chat.postMessage",
                bot_token,
                channel=dm_channel_id,
                text="You've been made Plans & BIA owner",
                **card,
            )
        else:
            text = (
                f":shield: You've been made *{module_label} admin* for *{org_name}* in TestMyPlan.\n"
                f"You now own setting up and running readiness tests for that module — head to "
                f"#testmyplan-command-center any time to review or change it."
            )
            _call("chat.postMessage", bot_token, channel=dm_channel_id, text=text)
    except SlackApiError:
        logger.exception("Failed to DM %s about %s admin assignment for team %s", target_slack_user_id, module_id, team_id)
