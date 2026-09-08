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


def build_bia_ready_card(plan) -> dict:
    """
    Real BIA-ready card built from an actual uploaded/parsed Plan --
    shared by both upload paths (drag-into-channel and the file-picker
    modal). Only shows RTO/RPO/contact fields B2's structured_extraction
    actually found; never fabricates numbers like the design prototype's
    fixed fake card did.
    """
    word_count = len(plan.extracted_text.split()) if plan.extracted_text else 0
    structured = plan.structured_data or {}
    rto_values = structured.get("rto") or []
    rpo_values = structured.get("rpo") or []
    email_count = len(structured.get("emails") or [])

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Business Continuity · BIA", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Plan ready*"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"BC plan drafted from *{plan.filename}* and ready to test (~{word_count} words parsed).",
            },
        },
    ]

    if rto_values or rpo_values or email_count:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Target RTO*\n{', '.join(rto_values) or '_not detected_'}"},
                    {"type": "mrkdwn", "text": f"*Target RPO*\n{', '.join(rpo_values) or '_not detected_'}"},
                    {"type": "mrkdwn", "text": f"*Contacts found*\n{email_count}"},
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "_No RTO/RPO or contacts detected -- this pattern-matching only catches phrasing like \"RTO: 4 hours\"._",
                    }
                ],
            }
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Show test scenarios", "emoji": True},
                    "action_id": "bia_scenarios",
                    "value": "next",
                    "style": "primary",
                }
            ],
        }
    )
    return {"blocks": blocks}


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
                "text": {"type": "mrkdwn", "text": f"*{team['team']}*\n`{team['module']}`"},
            }
        )
        for member in team["members"]:
            code = member["code"]
            value = f"{team['team']}:{member['role']}:{code}"
            is_added = code in added
            status = ":large_green_circle:" if is_added else ":bust_in_silhouette:"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{status} *{member['name']}*\n_{member['role']}_",
                    },
                    "accessory": {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Remove" if is_added else f"Add {member['name'].split()[0]}",
                            "emoji": True,
                        },
                        "action_id": "team_add",
                        "value": value,
                    },
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
                "text": f"*:bust_in_silhouette: {person['name']}*\n_{person['suggested_role']}_",
            },
            # A button as an "accessory" sits inline at the end of the row
            # instead of on its own line below -- reads as one compact row
            # per person rather than two stacked blocks each.
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": f"Add {person['name'].split()[0]}", "emoji": True},
                "action_id": "admin_expand",
                "value": person["code"],
            },
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
                "text": f":large_green_circle: *{person['name']}*\n`{module}`",
            },
            # Overflow ("...") menu instead of a single Remove button --
            # lets you change the module assignment without first removing
            # the person, which the old single-button version couldn't do.
            "accessory": {
                "type": "overflow",
                "action_id": "admin_overflow",
                "options": [
                    {"text": {"type": "plain_text", "text": "Change module"}, "value": f"{code}:change"},
                    {"text": {"type": "plain_text", "text": "Remove"}, "value": f"{code}:remove"},
                ],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Threat map (Step 3) -- sequential drill-down: category -> cause ->
# sub-cause -> scenario. Slack can't do a true accordion (several sections
# expanded independently at once, as the design mockup shows) -- this
# expands one thing at a time, replacing the card each click, same
# mechanism as the admin-team card's module picker.
#
# Only Business Continuity has real cause/sub-cause data below, matching
# what the design actually detailed. Other modules show a placeholder
# with a direct link to Upload BIA -- honest gap, not yet modeled.
# ---------------------------------------------------------------------------

THREAT_MODULES = ["Cybersecurity", "Privacy", "Business Continuity", "ESG", "Crisis Comms"]

THREATS_BY_MODULE = {
    "Business Continuity": [
        {
            "key": "infra",
            "label": "Infrastructure loss",
            "criticality": "Critical",
            "emoji": ":rotating_light:",
            "causes": [
                {
                    "key": "dc",
                    "label": "Data-center outage",
                    "subcauses": [
                        {"key": "power", "label": "Regional power / network failure"},
                        {"key": "cooling", "label": "Cooling / hardware failure"},
                    ],
                },
                {
                    "key": "app",
                    "label": "Critical system unavailable",
                    "subcauses": [{"key": "appcrash", "label": "Core application failure"}],
                },
            ],
        },
        {
            "key": "supwf",
            "label": "Supplier & workforce",
            "criticality": "High",
            "emoji": ":warning:",
            "causes": [],
        },
    ],
}

_MOST_CRITICAL = [
    ("Infrastructure loss", "Business Continuity", "infra"),
    ("External attacker", "Cybersecurity", None),
    ("Personal-data breach", "Privacy", None),
]


def _find_category(module: str, category_key: str) -> dict | None:
    for cat in THREATS_BY_MODULE.get(module, []):
        if cat["key"] == category_key:
            return cat
    return None


def _find_cause(module: str, category_key: str, cause_key: str) -> dict | None:
    category = _find_category(module, category_key)
    if not category:
        return None
    for cause in category["causes"]:
        if cause["key"] == cause_key:
            return cause
    return None


def build_threat_map_card(
    module: str = "Business Continuity", expanded_category: str = "", expanded_cause: str = "",
) -> dict:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Step 3 · Threat map", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": ":dart: *Ranked by criticality*"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Your organization's threats, the incidents that exploit them, and each incident's causes. Pick a cause to see its test scenarios.",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Most critical now*"}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"{label} · {mod[:3]}", "emoji": True},
                    "action_id": f"threat_jump__{i}",
                    "value": f"{mod}:{cat_key or ''}",
                }
                for i, (label, mod, cat_key) in enumerate(_MOST_CRITICAL)
            ],
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": m, "emoji": True},
                    "action_id": f"threat_module__{m.replace(' ', '_')}",
                    "value": m,
                    **({"style": "primary"} if m == module else {}),
                }
                for m in THREAT_MODULES
            ],
        },
        {"type": "divider"},
    ]

    categories = THREATS_BY_MODULE.get(module, [])
    if not categories:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"_No detailed threats mapped for {module} yet._",
                },
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip to Upload BIA", "emoji": True},
                        "action_id": "threat_open",
                        "value": module,
                        "style": "primary",
                    }
                ],
            }
        )
        return {"blocks": blocks}

    for category in categories:
        if category["key"] == expanded_category:
            blocks.extend(_expanded_category_blocks(module, category, expanded_cause))
        else:
            blocks.extend(_collapsed_category_blocks(module, category))
        blocks.append({"type": "divider"})

    return {"blocks": blocks}


def _collapsed_category_blocks(module: str, category: dict) -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{category['emoji']} *{category['label']}*  ·  {category['criticality']}\n{len(category['causes'])} incident(s)",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open incidents", "emoji": True},
                    # Unique per category -- more than one collapsed
                    # category can appear in the same card at once.
                    "action_id": f"threat_expand_category__{category['key']}",
                    "value": f"{module}:{category['key']}",
                }
            ],
        },
    ]


def _expanded_category_blocks(module: str, category: dict, expanded_cause: str) -> list:
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{category['emoji']} *{category['label']}*  ·  {category['criticality']}\n{len(category['causes'])} incident(s)",
            },
        }
    ]
    for cause in category["causes"]:
        if cause["key"] == expanded_cause:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{cause['label']}*\n" + "\n".join(f"• {s['label']}" for s in cause["subcauses"]),
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": f"Scenarios — {sc['label'][:24]}", "emoji": True},
                            "action_id": f"threat_scenarios__{sc['key']}",
                            "value": f"{module}:{category['key']}:{cause['key']}:{sc['key']}",
                            "style": "primary",
                        }
                        for sc in cause["subcauses"]
                    ],
                }
            )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{cause['label']}*\n{len(cause['subcauses'])} cause(s)"},
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View causes", "emoji": True},
                            # Unique per cause -- more than one un-expanded
                            # cause can appear under the same category.
                            "action_id": f"threat_expand_cause__{cause['key']}",
                            "value": f"{module}:{category['key']}:{cause['key']}",
                        }
                    ],
                }
            )
    return blocks
