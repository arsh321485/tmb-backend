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
    """
    Rendered as a real image, same template-code approach as
    role_card_image.py -- replaces the earlier static
    role_welcome_banner.png, which had "Welcome, Dikshika" baked in
    and would have shown THAT name to every single person instead of
    whoever was actually being welcomed. cards/welcome_card_image.py
    draws sir's design filled in with the real recipient name and
    real team/role, in well under a second.
    """
    from django.conf import settings

    from .welcome_card_image import get_welcome_card_image_url

    badge_label = "BACKUP" if is_backup else "RESPONSE TEAM"
    image_url = get_welcome_card_image_url(settings.BACKEND_URL, recipient_name, badge_label, f"{team_name} · {role}")

    return {
        "blocks": [
            {
                "type": "image",
                "image_url": image_url,
                "alt_text": f"Welcome, {recipient_name} — TestMyPlan",
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":rocket: View my role & responsibilities", "emoji": True},
                        "action_id": "v2_role_view",
                        "value": _value(catalog_team_id, role, is_backup),
                        "style": "primary",
                    }
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":bulb: No action needed right now — just review your role, then wait for the first task card."}],
            },
        ]
    }


def build_role_card(catalog_team_id: str, team_name: str, role: str, primary_name: str, backup_name: str, is_backup: bool, responsibility: dict | None, value: str) -> dict:
    """
    Rendered as a real image (sir's call -- same reasoning as the
    Welcome banner, but here the content itself is different for every
    person). cards/role_card_image.py draws sir's design (role name,
    team, Primary/Backup box, responsibility, one box per phase) filled
    in with THIS person's real data, in well under a second -- no AI
    image generation, no 150 hand-made picture files, works for any
    role.
    """
    from django.conf import settings

    from .role_activities_v2 import activities_for_role
    from .role_card_image import get_role_card_image_url

    # Real multi-row activity list for this role (sir's IR Team Catalog
    # spreadsheet, Roles sheet) -- the real activities this role
    # actually owns, across every phase, not just a single auto-mapped
    # action.
    activities = activities_for_role(catalog_team_id, role)
    phase_activities: list[tuple[str, list[str]]] = []
    real_responsibility = ""
    if activities:
        # Role Responsibilities column from the same spreadsheet row --
        # one text per role (repeats across that role's activity rows),
        # used once here rather than once per activity.
        real_responsibility = activities[0].get("responsibility", "")
        phases_seen: list[str] = []
        by_phase: dict[str, list[str]] = {}
        for a in activities:
            phase = a["phase"]
            if phase not in by_phase:
                by_phase[phase] = []
                phases_seen.append(phase)
            by_phase[phase].append(a["activity"])
        phase_activities = [(phase, by_phase[phase]) for phase in phases_seen]
    elif responsibility:
        real_responsibility = responsibility.get("text", "")
        action_detail = f"{responsibility.get('action', '')}: {responsibility.get('detail', '')}".strip(": ")
        phase = responsibility.get("phase", "")
        if action_detail:
            phase_activities = [(phase or "Your action", [action_detail])]

    backup_role_label = "PRIMARY" if is_backup else "BACKUP"
    backup_box_name = primary_name if is_backup else backup_name

    image_url = get_role_card_image_url(
        settings.BACKEND_URL, role, team_name, backup_role_label, backup_box_name or "", real_responsibility, phase_activities,
    )

    blocks = [
        {"type": "image", "image_url": image_url, "alt_text": f"Your role: {role}"},
    ]
    if is_backup:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":large_orange_circle: If the primary can't respond, you'd step in and run these activities."}]})
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Acknowledge my role", "emoji": True},
                    "action_id": "v2_role_acknowledge",
                    "value": value,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":no_entry_sign: I can't cover this role", "emoji": True},
                    "action_id": "v2_role_decline",
                    "value": value,
                },
            ],
        }
    )
    return {"blocks": blocks}


def build_ack_card(recipient_name: str, team_name: str, role: str, value: str) -> dict:
    """
    Rendered as a real image, same template-code approach as the
    Welcome and Role cards -- the sentence's role/team mentions are
    passed as highlighted chunks (cards/ack_card_image.py draws the
    pink highlight + bold text behind them), and the person's real
    name is drawn as the signature line at the bottom.
    """
    from django.conf import settings

    from .ack_card_image import get_ack_card_image_url

    sentence_parts = [
        ("I understand my role as ", False),
        (role, True),
        (" on ", False),
        (team_name, True),
        (". I've reviewed my responsibilities and I'm ready to respond when a test fires.", False),
    ]
    image_url = get_ack_card_image_url(settings.BACKEND_URL, sentence_parts, recipient_name)

    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "One last step"},
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":white_check_mark: I acknowledge — I'm ready", "emoji": True},
                        "action_id": "v2_role_ack_confirm",
                        "value": value,
                        "style": "primary",
                    }
                ],
            },
        ]
    }


def build_decline_done_card(team_name: str, role: str, backup_notified: bool) -> dict:
    note = (
        "Your backup has been notified and is now covering this role."
        if backup_notified
        else "No backup is on file for this role — the person who assigned you will need to find a replacement."
    )
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":no_entry_sign: *Marked as unable to cover {role} on {team_name}*"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]},
        ]
    }


def build_backup_activated_card(recipient_name: str, team_name: str, role: str, value: str) -> dict:
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: You're needed", "emoji": True}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi {recipient_name} — the primary for *{role}* on *{team_name}* can't cover it. As the named backup, you're now responsible for this role.",
                },
            },
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
            },
        ]
    }


def build_ack_done_card(acknowledged_at_text: str) -> dict:
    """Rendered as a real image, same template-code approach as the
    other three cards in this flow -- almost entirely static (same
    checkmark/heading/subtitle every time), only the logged timestamp
    actually varies per person."""
    from django.conf import settings

    from .ack_done_card_image import get_ack_done_card_image_url

    image_url = get_ack_done_card_image_url(settings.BACKEND_URL, acknowledged_at_text)
    return {"blocks": [{"type": "image", "image_url": image_url, "alt_text": "You're all set"}]}


def send_backup_activation_dm(recipient_slack_user_id: str, catalog_team_id: str, team_name: str, role: str, bot_token: str) -> bool:
    """Sent when the primary clicks "I can't cover this role" -- tells the
    named backup they're now responsible, with their own Acknowledge
    button (same value format the Welcome flow already recognizes, since
    they're being asked to acknowledge as the active person for this
    role, not merely the backup)."""
    if not (recipient_slack_user_id and bot_token):
        return False
    try:
        opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
        dm_channel_id = opened["channel"]["id"]
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}
        recipient_name = by_code.get(recipient_slack_user_id, {}).get("n", "there")

        value = _value(catalog_team_id, role, True)
        card = build_backup_activated_card(recipient_name, team_name, role, value)
        _call(
            "chat.postMessage",
            bot_token,
            channel=dm_channel_id,
            text=f"You're needed: the primary for {role} on {team_name} can't cover it.",
            **card,
        )
        return True
    except SlackApiError:
        logger.exception("Failed to send backup activation DM to %s for %s / %s", recipient_slack_user_id, team_name, role)
        return False


def send_reminder_dm(recipient_slack_user_id: str, team_name: str, role: str, hours: int, bot_token: str) -> bool:
    """24h/48h nudge for someone who hasn't acknowledged (or declined)
    their role yet -- they just never clicked anything."""
    if not (recipient_slack_user_id and bot_token):
        return False
    try:
        opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
        dm_channel_id = opened["channel"]["id"]
        text = (
            f":bell: Reminder — it's been {hours} hours and you haven't confirmed your role as "
            f"*{role}* on *{team_name}* yet. Please acknowledge it, or let us know if you can't cover it."
        )
        _call("chat.postMessage", bot_token, channel=dm_channel_id, text=text)
        return True
    except SlackApiError:
        logger.exception("Failed to send %sh reminder to %s for %s / %s", hours, recipient_slack_user_id, team_name, role)
        return False


def send_unreachable_escalation(slack_team_id: str, team_name: str, role: str, silent_user_id: str, bot_token: str) -> bool:
    """48h of total silence (no acknowledge, no decline) is treated the
    same as "can't cover it" for escalation purposes -- the role can't be
    left unconfirmed indefinitely just because nobody clicked a button."""
    from workspaces.models import get_first_admin

    owner_id = get_first_admin(slack_team_id)
    if not (owner_id and bot_token):
        return False
    try:
        opened = _call("conversations.open", bot_token, users=owner_id)
        dm_channel_id = opened["channel"]["id"]
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}
        silent_name = by_code.get(silent_user_id, {}).get("n", "Someone")

        text = (
            f":rotating_light: *{role}* on *{team_name}* — {silent_name} hasn't responded in 48 hours "
            f"(no acknowledge, no decline). Please follow up or reassign."
        )
        _call("chat.postMessage", bot_token, channel=dm_channel_id, text=text)
        return True
    except SlackApiError:
        logger.exception("Failed to notify first admin about unresponsive %s / %s", team_name, role)
        return False


def notify_module_owner_leaver(slack_team_id: str, team_name: str, role: str, leaver_user_id: str, bot_token: str) -> bool:
    """Someone assigned to a role is no longer in the workspace (left,
    deactivated, removed) -- proactively tells the first admin
    instead of leaving it to be noticed only if they happen to reopen the
    Teams & Roles setup card. By the time this fires, the person is
    already gone from the directory, so there's no name to look up --
    the role/team identifies the gap, and <@id> still renders something
    recognisable in Slack even for a removed user."""
    from workspaces.models import get_first_admin

    owner_id = get_first_admin(slack_team_id)
    if not (owner_id and bot_token):
        return False
    try:
        opened = _call("conversations.open", bot_token, users=owner_id)
        dm_channel_id = opened["channel"]["id"]
        text = (
            f":door: *{role}* on *{team_name}* — the person assigned (<@{leaver_user_id}>) is no longer "
            f"in the workspace. Please reassign this role."
        )
        _call("chat.postMessage", bot_token, channel=dm_channel_id, text=text)
        return True
    except SlackApiError:
        logger.exception("Failed to notify first admin about leaver on %s / %s", team_name, role)
        return False


def notify_module_owner_no_coverage(slack_team_id: str, team_name: str, role: str, declined_by_user_id: str, bot_token: str) -> bool:
    """Someone declined a role (v2_role_decline) and there was no backup
    to hand it to -- the first admin is the one real person who
    needs to know this role is now uncovered, since nothing else in the
    system will surface it otherwise."""
    from workspaces.models import get_first_admin

    owner_id = get_first_admin(slack_team_id)
    if not (owner_id and bot_token):
        return False
    try:
        opened = _call("conversations.open", bot_token, users=owner_id)
        dm_channel_id = opened["channel"]["id"]
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}
        decliner_name = by_code.get(declined_by_user_id, {}).get("n", "Someone")

        text = (
            f":rotating_light: *{role}* on *{team_name}* has no coverage — "
            f"{decliner_name} can't cover it and no backup is on file. Please reassign."
        )
        _call("chat.postMessage", bot_token, channel=dm_channel_id, text=text)
        return True
    except SlackApiError:
        logger.exception("Failed to notify first admin about uncovered role %s / %s", team_name, role)
        return False


def send_welcome_dm(
    recipient_slack_user_id: str, catalog_team_id: str, team_name: str, role: str, is_backup: bool, bot_token: str,
    existing_location: dict | None = None,
) -> dict:
    """
    No-op if there's no bot token -- not fatal either way.

    existing_location: {"channel_id", "message_ts"} of a Welcome DM
    already sent to this exact person for this exact role (from
    TeamMember.welcome_dm_location) -- when given, updates THAT same
    message in place instead of posting a brand new one, so
    re-assigning the same person (re-saving Configure Teams,
    re-testing, ...) doesn't leave stale duplicate Welcome messages
    stacked in their DM.

    Returns {"ok", "channel_id", "message_ts"} so the caller can save
    where this one landed for next time.
    """
    if not (recipient_slack_user_id and bot_token):
        return {"ok": False, "channel_id": "", "message_ts": ""}
    try:
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}
        recipient_name = by_code.get(recipient_slack_user_id, {}).get("n", "there")

        card = build_welcome_card(recipient_name, catalog_team_id, team_name, role, is_backup)

        if existing_location and existing_location.get("channel_id") and existing_location.get("message_ts"):
            dm_channel_id = existing_location["channel_id"]
            message_ts = existing_location["message_ts"]
            _call("chat.update", bot_token, channel=dm_channel_id, ts=message_ts, **card)
        else:
            opened = _call("conversations.open", bot_token, users=recipient_slack_user_id)
            dm_channel_id = opened["channel"]["id"]
            resp = _call(
                "chat.postMessage",
                bot_token,
                channel=dm_channel_id,
                text=f"You've been added to {team_name} as {role}.",
                **card,
            )
            message_ts = resp.get("ts", "")
        return {"ok": True, "channel_id": dm_channel_id, "message_ts": message_ts}
    except SlackApiError:
        logger.exception("Failed to send welcome DM to %s for %s / %s", recipient_slack_user_id, team_name, role)
        return {"ok": False, "channel_id": "", "message_ts": ""}
