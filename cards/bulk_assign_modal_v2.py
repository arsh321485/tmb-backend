"""
"Assign all at once" -- Teams card (Step 2). Closest thing Slack allows
to a table: one modal, one row per unstaffed mandatory team
(Role/Member/Backup side by side), filled and saved all at once instead
of opening each team individually.

Sir's call (brought back a second time): small companies don't have 35
different people to put on 35 different teams -- this makes it fast to
put the SAME 2-3 people (often just the founder/admin) across several
mandatory teams in one screen, instead of implying a different person is
needed per team.

Only covers the Mandatory tier -- that's the one that actually blocks
Continue; Recommended/Optional/External stay on the normal per-team flow.
"""

import json

import requests

from .team_catalog_v2 import MANDATORY_TEAM_IDS, find_team, roles_for_team
from .teams_v2_data import ROLE_CATALOG

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_bulk_assign_modal"


def _select_option(value: str, label: str | None = None) -> dict:
    return {"text": {"type": "plain_text", "text": (label or value)[:75]}, "value": value}


def _role_options(team_id: str) -> list:
    roles = roles_for_team(team_id)
    if roles:
        return [_select_option(r["role"], f"[{r['priority'][0]}] {r['role']}") for r in roles]
    return [_select_option(r) for r in ROLE_CATALOG]


def build_modal_view(people: list, teams_state: dict, channel_id: str = "", message_ts: str = "") -> dict:
    unstaffed_ids = [tid for tid in MANDATORY_TEAM_IDS if not teams_state.get(tid)]

    member_options = [{"text": {"type": "plain_text", "text": p["n"]}, "value": p["i"]} for p in people] or [
        {"text": {"type": "plain_text", "text": "No one in this workspace yet"}, "value": "__none__"}
    ]

    blocks = [
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "One row per unstaffed mandatory team. Fill what you can, leave the rest blank — Save only fills in complete rows. The same person can be picked across multiple rows."}
            ],
        },
    ]

    if not unstaffed_ids:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_Every mandatory team is already staffed._"}})
    else:
        for team_id in unstaffed_ids:
            team = find_team(team_id)
            blocks.append({"type": "divider"})
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{team_id} · {team['name']}*"}})
            blocks.append(
                {
                    "type": "input",
                    "block_id": f"bulkrole_{team_id}",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Role"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select role…"},
                        "options": _role_options(team_id),
                    },
                }
            )
            blocks.append(
                {
                    "type": "input",
                    "block_id": f"bulkmember_{team_id}",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Member"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select member…"},
                        "options": member_options,
                    },
                }
            )
            blocks.append(
                {
                    "type": "input",
                    "block_id": f"bulkbackup_{team_id}",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Backup member"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "Select backup…"},
                        "options": member_options,
                    },
                }
            )

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Assign all at once"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"channel_id": channel_id, "message_ts": message_ts}),
        "blocks": blocks,
    }


def open_modal(trigger_id: str, channel_id: str, message_ts: str, people: list, teams_state: dict, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(people, teams_state, channel_id, message_ts)},
        timeout=10,
    )


def parse_submission(payload: dict) -> list:
    """Returns [{"team_id", "role", "primary", "backup"}, ...] for every fully-filled row."""
    values = payload.get("view", {}).get("state", {}).get("values", {})
    rows = []
    for team_id in MANDATORY_TEAM_IDS:
        role_block = values.get(f"bulkrole_{team_id}", {}).get("value", {})
        member_block = values.get(f"bulkmember_{team_id}", {}).get("value", {})
        backup_block = values.get(f"bulkbackup_{team_id}", {}).get("value", {})

        role = (role_block.get("selected_option") or {}).get("value")
        primary = (member_block.get("selected_option") or {}).get("value")
        backup = (backup_block.get("selected_option") or {}).get("value")

        if role and primary and backup and primary != "__none__" and backup != "__none__":
            rows.append({"team_id": team_id, "role": role, "primary": primary, "backup": backup})

    return rows


def handle_submission(payload: dict, bot_token: str) -> None:
    from . import persistence_v2, team_assignment_notify_v2
    from .nav_v2 import with_nav_bar_v2
    from .slack_members_v2 import get_workspace_people
    from .team_catalog_v2 import default_responsibility_for
    from .teams_v2_data import ROLE_DEFAULT_RESP, build_teams_card

    team_id_slack = payload.get("team", {}).get("id", "")
    rows = parse_submission(payload)

    if rows:
        saved = persistence_v2.load_teams_state(team_id_slack)
        teams, resp = saved["teams"], saved["resp"]
        people = get_workspace_people(bot_token)
        by_code = {p["i"]: p for p in people}

        for row in rows:
            tid, role, primary, backup = row["team_id"], row["role"], row["primary"], row["backup"]
            teams.setdefault(tid, [])
            teams[tid].append({"role": role, "primary": [primary], "backup": [backup]})

            default_resp = default_responsibility_for(tid, role) or ROLE_DEFAULT_RESP.get(role)
            if default_resp:
                resp.setdefault(tid, [])
                resp[tid].append({"who": role, **default_resp})

        persistence_v2.save_teams_state(team_id_slack, teams, resp)

        for row in rows:
            tid, role, primary, backup = row["team_id"], row["role"], row["primary"], row["backup"]
            team = find_team(tid)
            team_name = team["name"] if team else tid
            default_resp = default_responsibility_for(tid, role) or ROLE_DEFAULT_RESP.get(role)
            team_assignment_notify_v2.send_team_assignment_dm(
                team_id_slack, team_name, role, primary, backup, default_resp, by_code, bot_token,
            )

    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id, message_ts = meta.get("channel_id", ""), meta.get("message_ts", "")
    if not (channel_id and message_ts and bot_token):
        return

    people = get_workspace_people(bot_token)
    state = persistence_v2.load_teams_state(team_id_slack)
    card = with_nav_bar_v2(build_teams_card(state, people), "teams")
    requests.post(
        f"{SLACK_API_BASE}/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    )
