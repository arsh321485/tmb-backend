"""
"Apply same user to other teams" -- real logic only now; the Slack
modal UI this used to have (Step 2's "Apply same user to other teams"
button) was removed per sir's call, moved to the website's Teams
portal instead (teams_portal.views.apply_same_user). This module keeps
just the real data-mutation + notification logic so the website can
call the exact same real behavior, not a reimplementation of it.

Applies a person from one team as Primary/Backup onto whichever of the
target team's own REAL unstaffed roles are still open -- never tries
to match role names (confirmed against the real 84-role catalog that
no two teams share an identical role name, so name-matching could
never legitimately apply anywhere).
"""

import logging

from .team_catalog_v2 import find_team, roles_for_team

logger = logging.getLogger(__name__)


def apply_to_other_teams(team_id_slack: str, source_team_id: str, source_role: str, target_ids: list, bot_token: str) -> list:
    """Applies source_team_id/source_role's real primary+backup onto
    every still-open role on each team in target_ids. Returns the real
    (target_id, role, primary_id, backup_id, responsibility) rows that
    got newly filled, so the caller can send the real Welcome DMs for
    them (not done here -- callers differ on how/when to do that)."""
    from . import persistence_v2
    from .team_catalog_v2 import default_responsibility_for

    newly_filled = []

    saved = persistence_v2.load_teams_state(team_id_slack)
    teams, resp = saved["teams"], saved["resp"]
    source_member = next((m for m in teams.get(source_team_id, []) if m["role"] == source_role), None)

    if not (source_member and source_member.get("primary")):
        return newly_filled

    primary_id = source_member["primary"][0]
    backup_id = source_member["backup"][0] if source_member.get("backup") else ""

    for target_id in target_ids:
        target_catalog_roles = [r["role"] for r in roles_for_team(target_id)]
        already_staffed = {m["role"] for m in teams.get(target_id, []) if m.get("primary")}
        open_roles = [r for r in target_catalog_roles if r not in already_staffed]

        for role in open_roles:
            teams.setdefault(target_id, [])
            existing = next((m for m in teams[target_id] if m["role"] == role), None)
            if existing is None:
                existing = {"role": role, "primary": [], "backup": []}
                teams[target_id].append(existing)
            existing["primary"] = [primary_id]
            if backup_id:
                existing["backup"] = [backup_id]

            default_resp = default_responsibility_for(target_id, role)
            if default_resp:
                resp.setdefault(target_id, [])
                resp[target_id] = [r for r in resp[target_id] if r.get("who") != role]
                resp[target_id].append({"who": role, **default_resp})

            newly_filled.append((target_id, role, primary_id, backup_id, default_resp))

    persistence_v2.save_teams_state(team_id_slack, teams, resp)
    return newly_filled


def send_notify_dms(team_id_slack: str, newly_filled: list, bot_token: str) -> None:
    """Real Welcome DM for each newly-filled (target_id, role) row --
    same as a direct assignment would trigger, just for every row this
    apply touched at once."""
    from . import team_assignment_notify_v2
    from .slack_members_v2 import get_workspace_people

    people = get_workspace_people(bot_token)
    by_code = {p["i"]: p for p in people}
    for target_id, role, primary_id, backup_id, default_resp in newly_filled:
        team_info = find_team(target_id)
        team_name = team_info["name"] if team_info else target_id
        try:
            team_assignment_notify_v2.send_team_assignment_dm(
                team_id_slack, team_name, role, primary_id, backup_id, default_resp, by_code, bot_token,
                catalog_team_id=target_id,
            )
        except Exception:
            logger.exception("send_team_assignment_dm failed in team_copy_modal_v2 for %s / %s", target_id, role)
