"""
A13-A17 -- the recurring check behind the 24h/48h "you haven't
acknowledged your role" reminder, and the 48h-silence escalation to the
first admin. Runs on the same daemon-thread pattern as
exercises/apps.py's drill-escalation checker (no Celery/cron in this
project).
"""

import datetime
import logging

from .models_v2 import Team, TeamMember

logger = logging.getLogger(__name__)

REMINDER_STAGES = (24, 48)

# Sir's call -- a PRIMARY who hasn't acknowledged or declined within this
# many minutes of the Welcome DM going out gets their backup activated
# automatically, same real activation as clicking "I can't cover this
# role" (role_welcome_v2.send_backup_activation_dm), just time-triggered.
# Deliberately much faster than the 24h/48h REMINDER_STAGES above, which
# is a separate, slower "alert the admin" path for total silence.
BACKUP_TIMEOUT_MINUTES = 20


def check_backup_timeout_activation() -> int:
    """
    For every PRIMARY a Welcome DM was sent to who hasn't acknowledged or
    declined within BACKUP_TIMEOUT_MINUTES, activates their real backup
    (same DM a decline sends) and marks it so this never fires twice for
    the same person. Returns how many backups were activated, for logging.
    """
    from . import role_welcome_v2
    from .team_catalog_v2 import find_team
    from workspaces.models import get_bot_token

    now = datetime.datetime.utcnow()
    activated_count = 0

    for tm in TeamMember.objects():
        pending_primaries = [
            uid
            for uid in tm.primary_slack_user_ids
            if (tm.dm_status or {}).get(uid) == "sent"
            and uid not in (tm.acknowledged_by or {})
            and uid not in (tm.declined_by or {})
            and uid not in (tm.backup_timeout_activated or {})
        ]
        if not pending_primaries:
            continue

        team_doc = tm.team
        if not isinstance(team_doc, Team):
            team_doc = Team.objects(id=tm.team.id).first()
        if not team_doc:
            continue

        bot_token = get_bot_token(team_doc.team_id)
        if not bot_token:
            continue

        team_info = find_team(team_doc.slug)
        team_name = team_info["name"] if team_info else team_doc.name

        changed = False
        for uid in pending_primaries:
            sent_at = tm.dm_sent_at.get(uid)
            if not sent_at:
                continue
            elapsed_minutes = (now - sent_at).total_seconds() / 60
            if elapsed_minutes < BACKUP_TIMEOUT_MINUTES:
                continue

            backup_ids = [b for b in tm.backup_slack_user_ids if b != uid]
            if backup_ids:
                role_welcome_v2.send_backup_activation_dm(backup_ids[0], team_doc.slug, team_name, tm.role, bot_token)
            tm.backup_timeout_activated[uid] = now
            activated_count += 1
            changed = True

        if changed:
            tm.save()

    return activated_count


def check_role_reminders() -> int:
    """
    For everyone a Welcome DM was actually sent to (dm_status == "sent")
    who hasn't acknowledged or declined yet: sends the 24h and 48h
    reminder DMs once each, and once 48h of total silence has passed,
    alerts the first admin so the gap doesn't go unnoticed.

    Returns how many reminder/escalation messages were sent, for logging.
    """
    from . import role_welcome_v2
    from .team_catalog_v2 import find_team
    from workspaces.models import get_bot_token

    now = datetime.datetime.utcnow()
    sent_count = 0

    for tm in TeamMember.objects():
        pending = [
            uid
            for uid, status in (tm.dm_status or {}).items()
            if status == "sent" and uid not in (tm.acknowledged_by or {}) and uid not in (tm.declined_by or {})
        ]
        if not pending:
            continue

        team_doc = tm.team
        if not isinstance(team_doc, Team):
            team_doc = Team.objects(id=tm.team.id).first()
        if not team_doc:
            continue

        bot_token = get_bot_token(team_doc.team_id)
        if not bot_token:
            continue

        team_info = find_team(team_doc.slug)
        team_name = team_info["name"] if team_info else team_doc.name

        changed = False
        for uid in pending:
            sent_at = tm.dm_sent_at.get(uid)
            if not sent_at:
                continue
            elapsed_hours = (now - sent_at).total_seconds() / 3600
            stages_done = tm.reminders_sent.get(uid, [])

            for stage in REMINDER_STAGES:
                if elapsed_hours >= stage and str(stage) not in stages_done:
                    if stage == 48:
                        ok = role_welcome_v2.send_unreachable_escalation(team_doc.team_id, team_name, tm.role, uid, bot_token)
                    else:
                        ok = role_welcome_v2.send_reminder_dm(uid, team_name, tm.role, stage, bot_token)
                    if ok:
                        sent_count += 1
                    stages_done.append(str(stage))
                    tm.reminders_sent[uid] = stages_done
                    changed = True

        if changed:
            tm.save()

    return sent_count


def check_leavers() -> int:
    """
    For every team, compares each role's assigned primary/backup slack
    ids against the workspace's current member list -- anyone assigned
    who's no longer a member gets reported to the first admin
    once (leaver_notified guards against repeating the same alert every
    minute). This is what makes the Teams & Roles leaver warning
    proactive instead of something the admin only sees by reopening that
    card themselves.
    """
    from . import role_welcome_v2
    from .slack_members_v2 import get_workspace_people
    from .team_catalog_v2 import find_team
    from workspaces.models import get_bot_token

    sent_count = 0
    team_ids = Team.objects().distinct("team_id")

    for slack_team_id in team_ids:
        bot_token = get_bot_token(slack_team_id)
        if not bot_token:
            continue

        current_member_ids = {p["i"] for p in get_workspace_people(bot_token)}

        for team_doc in Team.objects(team_id=slack_team_id):
            team_info = find_team(team_doc.slug)
            team_name = team_info["name"] if team_info else team_doc.name

            for tm in TeamMember.objects(team=team_doc):
                assigned_ids = set(tm.primary_slack_user_ids) | set(tm.backup_slack_user_ids)
                already_notified = set(tm.leaver_notified or [])
                left_ids = [uid for uid in assigned_ids if uid not in current_member_ids and uid not in already_notified]
                if not left_ids:
                    continue

                changed = False
                for uid in left_ids:
                    ok = role_welcome_v2.notify_module_owner_leaver(slack_team_id, team_name, tm.role, uid, bot_token)
                    if ok:
                        sent_count += 1
                        tm.leaver_notified.append(uid)
                        changed = True
                if changed:
                    tm.save()

    return sent_count
