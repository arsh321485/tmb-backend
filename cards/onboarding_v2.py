"""
Real onboarding flow for new workspace installs (sir approved deleting
the old command-center wizard and replacing it with this new design,
see cards/blocks_v2/ and cards/*_v2.py). Creates #testmyplan-command-center
and posts the Welcome + Organizational Threats cards into it.
"""

import logging

from .slack_client import SlackApiError, _call, post_card_to_channel

logger = logging.getLogger(__name__)

PREVIEW_CHANNEL_NAME = "testmyplan-command-center"


def _real_user_name(slack_user_id: str, bot_token: str) -> str:
    if not slack_user_id or not bot_token:
        return "there"
    try:
        import requests

        # users.info doesn't reliably accept JSON-POST params (confirmed
        # live: returned "user_not_found" for a real, valid user id even
        # though users.list shows them) -- needs GET + query params,
        # same fix as slack_members_v2.py's users.list call.
        resp = requests.get(
            "https://slack.com/api/users.info",
            headers={"Authorization": f"Bearer {bot_token}"},
            params={"user": slack_user_id},
            timeout=10,
        ).json()
        if not resp.get("ok"):
            return "there"
        profile = resp.get("user", {}).get("profile", {})
        return profile.get("real_name") or resp.get("user", {}).get("name", "there")
    except Exception:
        return "there"


def welcome_card_replacements(team_id: str, installer_slack_user_id: str, bot_token: str) -> dict:
    from workspaces.models import Workspace

    workspace = Workspace.objects(team_id=team_id).first()
    team_name = (workspace.team_name if workspace else "") or "your organization"
    user_name = _real_user_name(installer_slack_user_id, bot_token)
    return {"TEAM_NAME": team_name, "USER_NAME": user_name}


def build_admin_welcome_card(team_id: str, installer_slack_user_id: str, bot_token: str) -> dict:
    """Rendered as a real image (sir's admin-side "Welcome to
    TestMyPlan" design), same template-code approach as the other
    cards -- only the installer's real name actually varies; the
    4-step overview is identical for everyone. "Get started" stays a
    real button underneath it."""
    from django.conf import settings

    from .admin_welcome_card_image import get_admin_welcome_card_image_url

    replacements = welcome_card_replacements(team_id, installer_slack_user_id, bot_token)
    image_url = get_admin_welcome_card_image_url(settings.BACKEND_URL, replacements["USER_NAME"])
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Welcome to TestMyPlan"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":rocket: Get started", "emoji": True},
                        "action_id": "v2_welcome_next",
                        "value": "next",
                        "style": "primary",
                    }
                ],
            },
        ]
    }


def ensure_preview_channel(team_id: str, bot_token: str) -> str:
    """
    Cached on the Workspace record the moment it's created, so a later
    call never needs conversations.list to re-find it -- several already-
    installed workspaces predate the channels:read scope that requires,
    and would fail every time otherwise (confirmed live: "missing_scope").
    """
    from workspaces.models import Workspace

    workspace = Workspace.objects(team_id=team_id).first()
    if workspace and workspace.new_design_preview_channel_id:
        return workspace.new_design_preview_channel_id

    try:
        # Private -- confirmed live: a public admin channel let a newly
        # invited regular team member ("automate") see and self-join it
        # via Slack's own "Join Channel" button, exposing every admin
        # setup card to them. Private channels don't offer that at all;
        # only people explicitly invited (the admin) can see it.
        created = _call("conversations.create", bot_token, name=PREVIEW_CHANNEL_NAME, is_private=True)
        channel_id = created["channel"]["id"]
    except SlackApiError as exc:
        if str(exc) != "name_taken":
            raise
        # Channel already exists (e.g. created before this caching existed)
        # but we have no scope to look it up -- nothing more we can do
        # here short of a reinstall to pick up channels:read.
        raise SlackApiError("preview_channel_exists_but_unknown_id")

    if workspace:
        workspace.new_design_preview_channel_id = channel_id
        workspace.save()

    return channel_id


def send_new_design_preview(team_id: str, installer_slack_user_id: str, bot_token: str) -> None:
    """
    Called on every new workspace install -- creates #testmyplan-command-center,
    invites the installer, and posts the Welcome card (which itself leads
    into Threats, Admins, Teams, etc. via the nav bar / button clicks).
    """
    try:
        channel_id = ensure_preview_channel(team_id, bot_token)

        if installer_slack_user_id:
            try:
                _call("conversations.invite", bot_token, channel=channel_id, users=installer_slack_user_id)
            except SlackApiError:
                pass  # already a member, or can't invite -- not fatal

        from .nav_v2 import with_nav_bar_v2

        card = with_nav_bar_v2(build_admin_welcome_card(team_id, installer_slack_user_id, bot_token), "welcome")
        post_card_to_channel(channel_id, card, bot_token)
    except SlackApiError:
        logger.exception("Failed to post new-design welcome card for team %s", team_id)
