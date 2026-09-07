"""
Renders the admin-team card from real tracked state (WizardState),
instead of the static prototype JSON as-is.

Each person can be in one of 3 states:
- collapsed, not added: just an "Add" button
- expanded: picking which module they're admin for, before confirming
  (their own choice, independent of the other 3 people)
- collapsed, added: shows which module they were confirmed for, with a
  single button that removes them again (no separate delete button --
  the same click undoes it)

Note: a colored highlight/background for the "added" row (as in the
prototype) isn't possible -- Slack section blocks don't support custom
backgrounds. The checkmark and module label are the real equivalent.
"""

PEOPLE = [
    {"code": "PA", "name": "Priya Adeyemi", "suggested_role": "Risk & Compliance"},
    {"code": "MC", "name": "Marco Castellanos", "suggested_role": "Privacy Counsel"},
    {"code": "JW", "name": "James Whitfield", "suggested_role": "Infrastructure / BC"},
    {"code": "LB", "name": "Lena Bianchi", "suggested_role": "Communications"},
]
MODULES = ["All modules", "Cybersecurity", "Privacy", "Business Continuity", "ESG", "Crisis Comms"]

RESPONSE_TEAMS = [
    {
        "team": "Incident Response Team",
        "module": "Cybersecurity",
        "members": [
            {"code": "SR", "name": "Sofia Reyes", "role": "IR Lead"},
            {"code": "TK", "name": "Tomas Kruger", "role": "SOC Analyst"},
        ],
    },
    {
        "team": "Business Continuity Team",
        "module": "Business Continuity",
        "members": [
            {"code": "JW", "name": "James Whitfield", "role": "BC Lead"},
            {"code": "KS", "name": "Kenji Sato", "role": "IT Operations"},
        ],
    },
    {
        "team": "Privacy Response Team",
        "module": "Privacy",
        "members": [{"code": "MC", "name": "Marco Castellanos", "role": "Privacy Counsel"}],
    },
    {
        "team": "Crisis Comms Team",
        "module": "Crisis Comms",
        "members": [{"code": "LB", "name": "Lena Bianchi", "role": "Comms Lead"}],
    },
]
RESPONSE_TEAM_MEMBER_COUNT = sum(len(t["members"]) for t in RESPONSE_TEAMS)


def build_response_teams_card(team_id: str, org_name: str = "") -> dict:
    from .models import get_or_create_state

    state = get_or_create_state(team_id)
    added = set(state.response_members_added)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Step 2 · Response teams", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":shield: *Mandatory teams*  ·  {len(added)} / {RESPONSE_TEAM_MEMBER_COUNT} filled",
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Add each member -- {org_name or 'your org'} teams are tracked here. "
                    "You can also build your own teams for anything else."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Add all suggested members", "emoji": True},
                    "action_id": "team_add_all",
                    "value": "all",
                }
            ],
        },
        {"type": "divider"},
    ]

    for team in RESPONSE_TEAMS:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{team['team']}*\n{team['module']}"},
            }
        )
        for member in team["members"]:
            code = member["code"]
            value = f"{team['team']}:{member['role']}:{code}"
            is_added = code in added
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*:bust_in_silhouette: {member['name']}* — {member['role']}",
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "✓ Notified — click to remove" if is_added else f"Add {member['name'].split()[0]}",
                                "emoji": True,
                            },
                            "action_id": "team_add",
                            "value": value,
                        }
                    ],
                }
            )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Create a team", "emoji": True},
                    "action_id": "team_create",
                    "value": "open",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Teams ready — show my threat map", "emoji": True},
                    "action_id": "teams_done",
                    "value": "next",
                    "style": "primary",
                },
            ],
        }
    )

    return {"blocks": blocks}


def build_admin_team_card(
    team_id: str, org_name: str = "", person_name: str = "",
    expanded_code: str = "", selected_module: str = "",
) -> dict:
    from .models import get_or_create_state

    state = get_or_create_state(team_id)
    admin_modules = state.admin_modules or {}

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Step 1 · Admin team", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":busts_in_silhouette: *Share the load*  ·  {len(admin_modules)} added",
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Each admin can run every module, or only the ones under their responsibility.",
            },
        },
        {"type": "divider"},
    ]

    for person in PEOPLE:
        code = person["code"]
        if code == expanded_code:
            blocks.extend(_expanded_person_blocks(person, selected_module or "All modules"))
        elif code in admin_modules:
            blocks.extend(_confirmed_person_blocks(person, admin_modules[code]))
        else:
            blocks.extend(_collapsed_person_blocks(person))
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Continue — set up response teams", "emoji": True},
                    "action_id": "admin_done",
                    "value": "next",
                    "style": "primary",
                }
            ],
        }
    )

    return {"blocks": blocks}


def _collapsed_person_blocks(person: dict) -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*:bust_in_silhouette: {person['name']}*\n{person['suggested_role']}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Add {person['name'].split()[0]}", "emoji": True},
                    "action_id": "admin_expand",
                    "value": person["code"],
                }
            ],
        },
    ]


def _expanded_person_blocks(person: dict, selected_module: str) -> list:
    code = person["code"]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*:bust_in_silhouette: {person['name']}*\n{person['suggested_role']}",
            },
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "*Module responsibility*"}]},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": module, "emoji": True},
                    # action_id must be unique per message -- give each
                    # module button its own (see the "invalid_blocks" fix
                    # applied elsewhere for the same underlying mistake).
                    "action_id": f"admin_pick_module__{module.replace(' ', '_')}",
                    "value": f"{code}:{module}",
                    **({"style": "primary"} if module == selected_module else {}),
                }
                for module in MODULES
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"+ Add as admin ({selected_module})", "emoji": True},
                    "action_id": "admin_confirm",
                    "value": f"{code}:{selected_module}",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "admin_cancel",
                    "value": code,
                },
            ],
        },
    ]


def _confirmed_person_blocks(person: dict, module: str) -> list:
    code = person["code"]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *{person['name']}*\n_{module}_",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✓ Admin — click to remove", "emoji": True},
                    "action_id": "admin_add",
                    "value": code,
                }
            ],
        },
    ]
