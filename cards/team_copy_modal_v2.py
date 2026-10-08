"""
"Copy to other teams" -- Teams card (Step 2). Sir's call: a small
company's 2-3 IT people run every team, so once one team's Role/Member/
Backup is filled in, let the admin copy that exact same assignment onto
sibling teams instead of re-entering it per team.

A modal, not inline checkboxes -- a plain Slack message has no reliable
way to carry a checkbox's checked state from one click to the next (it
just echoes back whatever we last rendered), so an inline
checkboxes-then-button flow silently loses the selection. A modal's
view_submission carries its own state reliably, same reasoning as
bulk_assign_modal_v2.
"""

import json

import requests

from .team_catalog_v2 import ALL_TEAMS, find_team

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_team_copy_modal"


def build_modal_view(source_team_id: str, channel_id: str = "", message_ts: str = "") -> dict:
    source_team = find_team(source_team_id)
    siblings = [t for t in ALL_TEAMS if t["tier"] == (source_team or {}).get("tier") and t["id"] != source_team_id]

    options = [
        {"text": {"type": "plain_text", "text": f"{t['id']} · {t['name']}"[:75]}, "value": t["id"]}
        for t in siblings
    ]

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Apply to other teams"},
        "submit": {"type": "plain_text", "text": "Apply"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"source_team_id": source_team_id, "channel_id": channel_id, "message_ts": message_ts}),
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Applies *{source_team_id} · {(source_team or {}).get('name', '')}*'s current Role/Member/Backup assignment onto every team picked below, overwriting whatever that team already has.",
                },
            },
            {
                "type": "input",
                "block_id": "targets",
                "label": {"type": "plain_text", "text": "Apply to"},
                "element": {
                    "type": "multi_static_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Select teams…"},
                    "options": options,
                },
            },
        ],
    }


def open_modal(trigger_id: str, source_team_id: str, channel_id: str, message_ts: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(source_team_id, channel_id, message_ts)},
        timeout=10,
    )


def parse_submission(payload: dict) -> tuple[str, list]:
    """Returns (source_team_id, [target_team_id, ...])."""
    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    source_team_id = meta.get("source_team_id", "")

    values = payload.get("view", {}).get("state", {}).get("values", {})
    selected = values.get("targets", {}).get("value", {}).get("selected_options") or []
    target_ids = [o.get("value") for o in selected if o.get("value")]
    return source_team_id, target_ids


def handle_submission(payload: dict, bot_token: str) -> None:
    import logging

    from . import persistence_v2, team_assignment_notify_v2
    from .nav_v2 import with_nav_bar_v2
    from .slack_members_v2 import get_workspace_people
    from .teams_v2_data import build_teams_card

    logger = logging.getLogger(__name__)

    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id, message_ts = meta.get("channel_id", ""), meta.get("message_ts", "")

    team_id_slack = payload.get("team", {}).get("id", "")
    source_team_id, target_ids = parse_submission(payload)

    source_members, source_resp = [], []
    if source_team_id and target_ids:
        saved = persistence_v2.load_teams_state(team_id_slack)
        teams, resp = saved["teams"], saved["resp"]
        source_members = teams.get(source_team_id, [])
        source_resp = resp.get(source_team_id, [])

        for target_id in target_ids:
            teams[target_id] = [dict(m) for m in source_members]
            if source_resp:
                resp[target_id] = [dict(r) for r in source_resp]
        persistence_v2.save_teams_state(team_id_slack, teams, resp)

    # Update the card right away -- the DMs below are several blocking
    # Slack API calls (one per member per target team) and used to run
    # BEFORE this update, which is why "Copy" felt like it took 5-10
    # seconds to actually show anything. The admin doesn't need to wait
    # on DM delivery to see their own copy succeed.
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

    if source_team_id and target_ids and source_members:
        import threading

        def _send_dms():
            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            for target_id in target_ids:
                team_info = find_team(target_id)
                team_name = team_info["name"] if team_info else target_id
                for member in source_members:
                    primary_id = member["primary"][0] if member["primary"] else ""
                    backup_id = member["backup"][0] if member["backup"] else ""
                    if not primary_id:
                        continue
                    default_resp = next((r for r in source_resp if r.get("who") == member["role"]), None)
                    try:
                        team_assignment_notify_v2.send_team_assignment_dm(
                            team_id_slack, team_name, member["role"], primary_id, backup_id, default_resp, by_code, bot_token,
                        )
                    except Exception:
                        logger.exception("send_team_assignment_dm failed in team_copy_modal_v2 for %s", target_id)

        threading.Thread(target=_send_dms, daemon=True).start()
