"""
"Apply same user to other teams" -- Teams card (Step 2). Sir's call: a
small company's 2-3 IT people run every team, so once someone is staffed
on one team, let the admin put that SAME PERSON onto other teams too,
without re-picking them from scratch each time.

Redesigned from an earlier version that copied a role by NAME onto
sibling teams -- confirmed against the real 84-role catalog that no two
teams share an identical role name at all, so that approach could never
legitimately apply anywhere; it only ever "worked" by silently pasting a
role onto a team that doesn't really have it (e.g. "Incident Commander"
ended up copied onto IT Operations, which has no such role). This version
never tries to match role names -- it applies the chosen person as
Primary/Backup onto whichever of the target team's own REAL unstaffed
roles are still open, which is what "same person, different team" should
have meant all along.

A modal, not inline checkboxes -- a plain Slack message has no reliable
way to carry a checkbox's checked state from one click to the next (it
just echoes back whatever we last rendered), so an inline
checkboxes-then-button flow silently loses the selection. A modal's
view_submission carries its own state reliably, same reasoning as
bulk_assign_modal_v2.
"""

import json

import requests

from .team_catalog_v2 import ALL_TEAMS, find_team, roles_for_team

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_team_copy_modal"


def build_modal_view(source_team_id: str, channel_id: str = "", message_ts: str = "", slack_team_id: str = "") -> dict:
    from . import persistence_v2

    source_team = find_team(source_team_id)
    source_members = []
    if slack_team_id:
        saved = persistence_v2.load_teams_state(slack_team_id)
        source_members = [m for m in saved["teams"].get(source_team_id, []) if m.get("primary")]

    siblings = [t for t in ALL_TEAMS if t["tier"] == (source_team or {}).get("tier") and t["id"] != source_team_id]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Applies a person from *{source_team_id} · {(source_team or {}).get('name', '')}* as Primary/Backup onto every still-open role on the team(s) picked below.",
            },
        }
    ]

    if not source_members:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_This team has nobody assigned yet -- staff a role here first._"}})
        return {
            "type": "modal",
            "callback_id": CALLBACK_ID,
            "title": {"type": "plain_text", "text": "Apply same user"},
            "close": {"type": "plain_text", "text": "Close"},
            "private_metadata": json.dumps({"source_team_id": source_team_id, "channel_id": channel_id, "message_ts": message_ts}),
            "blocks": blocks,
        }

    if not siblings:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No other team in this tier to apply onto._"}})
        return {
            "type": "modal",
            "callback_id": CALLBACK_ID,
            "title": {"type": "plain_text", "text": "Apply same user"},
            "close": {"type": "plain_text", "text": "Close"},
            "private_metadata": json.dumps({"source_team_id": source_team_id, "channel_id": channel_id, "message_ts": message_ts}),
            "blocks": blocks,
        }

    # Which real assignment on the source team to apply -- the person is
    # what gets carried over, not the role name (the target team almost
    # certainly doesn't have this exact role).
    role_options = [{"text": {"type": "plain_text", "text": m["role"][:75]}, "value": m["role"]} for m in source_members]
    blocks.append(
        {
            "type": "input",
            "block_id": "source_role",
            "label": {"type": "plain_text", "text": "Apply this person"},
            "element": {
                "type": "static_select",
                "action_id": "value",
                "placeholder": {"type": "plain_text", "text": "Select a staffed role…"},
                "options": role_options,
                **({"initial_option": role_options[0]} if len(role_options) == 1 else {}),
            },
        }
    )

    target_options = [
        {"text": {"type": "plain_text", "text": f"{t['id']} · {t['name']}"[:75]}, "value": t["id"]}
        for t in siblings
    ]
    blocks.append(
        {
            "type": "input",
            "block_id": "targets",
            "label": {"type": "plain_text", "text": "Apply to"},
            "element": {
                "type": "multi_static_select",
                "action_id": "value",
                "placeholder": {"type": "plain_text", "text": "Select teams…"},
                "options": target_options,
            },
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Fills every role on the selected team(s) that doesn't already have someone assigned -- doesn't overwrite existing assignments."}],
        }
    )

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Apply same user"},
        "submit": {"type": "plain_text", "text": "Apply"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"source_team_id": source_team_id, "channel_id": channel_id, "message_ts": message_ts}),
        "blocks": blocks,
    }


def open_modal(trigger_id: str, source_team_id: str, channel_id: str, message_ts: str, bot_token: str, slack_team_id: str = "") -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(source_team_id, channel_id, message_ts, slack_team_id=slack_team_id)},
        timeout=10,
    )


def parse_submission(payload: dict) -> tuple[str, str, list]:
    """Returns (source_team_id, source_role, [target_team_id, ...])."""
    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    source_team_id = meta.get("source_team_id", "")

    values = payload.get("view", {}).get("state", {}).get("values", {})
    source_role = (values.get("source_role", {}).get("value", {}).get("selected_option") or {}).get("value", "")
    selected = values.get("targets", {}).get("value", {}).get("selected_options") or []
    target_ids = [o.get("value") for o in selected if o.get("value")]
    return source_team_id, source_role, target_ids


def handle_submission(payload: dict, bot_token: str) -> None:
    import logging

    from . import persistence_v2, team_assignment_notify_v2
    from .nav_v2 import with_nav_bar_v2
    from .slack_members_v2 import get_workspace_people
    from .teams_v2_data import build_teams_card
    from .team_catalog_v2 import default_responsibility_for

    logger = logging.getLogger(__name__)

    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id, message_ts = meta.get("channel_id", ""), meta.get("message_ts", "")

    team_id_slack = payload.get("team", {}).get("id", "")
    source_team_id, source_role, target_ids = parse_submission(payload)

    # (target_id, role) -> (primary_id, backup_id) that actually got
    # newly filled, for the DM step below.
    newly_filled = []

    if source_team_id and source_role and target_ids:
        saved = persistence_v2.load_teams_state(team_id_slack)
        teams, resp = saved["teams"], saved["resp"]
        source_member = next((m for m in teams.get(source_team_id, []) if m["role"] == source_role), None)

        if source_member and source_member.get("primary"):
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

    # Update the card right away -- the DMs below are several blocking
    # Slack API calls and used to run BEFORE this update, which is why
    # "Apply" felt like it took 5-10 seconds to show anything. The admin
    # doesn't need to wait on DM delivery to see their own copy succeed.
    if channel_id and message_ts and bot_token:
        people = get_workspace_people(bot_token)
        state = persistence_v2.load_teams_state(team_id_slack)
        card = with_nav_bar_v2(build_teams_card(state, people), "teams")
        resp_json = requests.post(
            f"{SLACK_API_BASE}/chat.update",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel_id, "ts": message_ts, **card},
            timeout=10,
        ).json()
        if not resp_json.get("ok"):
            logger.warning("chat.update failed in team_copy_modal_v2: %s", resp_json)

    if newly_filled:
        import threading

        def _send_dms():
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

        threading.Thread(target=_send_dms, daemon=True).start()
