"""
The "Create a team" button opens a real Slack modal (a popup form) --
unlike regular channel cards, modals support proper form inputs.

Matches the design's real intent: assign a *role* to each individual
member one at a time ("Priya = IR Lead", "Marco = SOC Analyst"), not
just a flat list of members. Slack modals support this via a
dynamic-update pattern: clicking "+ Add member" doesn't submit the
modal, it calls views.update to redraw the same modal with that
assignment added to a running list, plus a fresh empty role/member
picker for the next one. The list itself is carried in the modal's
private_metadata (JSON) between updates, since Slack doesn't persist
state across view.update calls on its own.
"""

import json

import requests

from .models import CustomTeam, get_or_create_state

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "create_team_modal"

MODULE_OPTIONS = ["Cybersecurity", "Privacy", "Business Continuity", "ESG", "Crisis Comms"]
ROLE_OPTIONS = [
    "IR Lead", "SOC Analyst", "BC Lead", "IT Operations",
    "Privacy Counsel", "Comms Lead", "Recovery Lead",
]


def _metadata(channel_id: str, assignments: list) -> str:
    return json.dumps({"channel_id": channel_id, "assignments": assignments})


def _parse_metadata(view: dict) -> tuple[str, list]:
    try:
        data = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        data = {}
    return data.get("channel_id", ""), data.get("assignments", [])


def build_modal_view(channel_id: str, assignments: list) -> dict:
    blocks = [
        {
            "type": "input",
            "block_id": "team_name",
            "label": {"type": "plain_text", "text": "Team name"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "module",
            "label": {"type": "plain_text", "text": "Module"},
            "optional": True,
            "element": {
                "type": "static_select",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": m}, "value": m}
                    for m in MODULE_OPTIONS
                ],
            },
        },
        {"type": "divider"},
    ]

    for assignment in assignments:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{assignment['role']}*\n<@{assignment['member']}>",
                },
            }
        )

    blocks.extend(
        [
            {
                "type": "input",
                "block_id": "new_role",
                "label": {"type": "plain_text", "text": "Role"},
                "optional": True,
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [
                        {"text": {"type": "plain_text", "text": r}, "value": r}
                        for r in ROLE_OPTIONS
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "new_member",
                "label": {"type": "plain_text", "text": "Assign to"},
                "optional": True,
                "element": {"type": "users_select", "action_id": "value"},
            },
            {
                "type": "actions",
                "block_id": "add_member_row",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Add member"},
                        "action_id": "modal_add_member",
                    }
                ],
            },
        ]
    )

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": _metadata(channel_id, assignments),
        "title": {"type": "plain_text", "text": "Create a team"},
        "submit": {"type": "plain_text", "text": "Create team"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def open_modal(trigger_id: str, channel_id: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(channel_id, [])},
        timeout=10,
    )


def handle_add_member_click(payload: dict, bot_token: str) -> None:
    """'+ Add member' inside the modal -- redraws the modal with the new row added."""
    view = payload.get("view", {})
    channel_id, assignments = _parse_metadata(view)

    values = view.get("state", {}).get("values", {})
    role_option = values.get("new_role", {}).get("value", {}).get("selected_option")
    member_id = values.get("new_member", {}).get("value", {}).get("selected_user")

    if role_option and member_id:
        assignments = assignments + [{"role": role_option["value"], "member": member_id}]

    new_view = build_modal_view(channel_id, assignments)
    # Keep whatever the user already typed for team name / module.
    team_name_value = values.get("team_name", {}).get("value", {}).get("value")
    if team_name_value:
        new_view["blocks"][0]["element"]["initial_value"] = team_name_value
    module_option = values.get("module", {}).get("value", {}).get("selected_option")
    if module_option:
        new_view["blocks"][1]["element"]["initial_option"] = module_option

    requests.post(
        f"{SLACK_API_BASE}/views.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"view_id": view.get("id"), "hash": view.get("hash"), "view": new_view},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    """The modal's own 'Create team' submit button (view_submission)."""
    view = payload.get("view", {})
    team_id = payload.get("team", {}).get("id", "")
    channel_id, assignments = _parse_metadata(view)

    values = view.get("state", {}).get("values", {})
    name = values.get("team_name", {}).get("value", {}).get("value", "").strip()
    module_option = values.get("module", {}).get("value", {}).get("selected_option")
    module = module_option["value"] if module_option else None

    if not name:
        return

    state = get_or_create_state(team_id)
    state.custom_teams.append(
        CustomTeam(
            name=name,
            module=module,
            member_slack_user_ids=[a["member"] for a in assignments],
            role_assignments=assignments,
        )
    )
    state.save()

    if channel_id:
        if assignments:
            lines = "\n".join(f"• *{a['role']}*: <@{a['member']}>" for a in assignments)
            text = f":white_check_mark: Team *{name}* created:\n{lines}"
        else:
            text = f":white_check_mark: Team *{name}* created."
        requests.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel_id, "text": text},
            timeout=10,
        )
