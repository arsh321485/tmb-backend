"""
Shared data + card-building for the new-design preview's "Response
teams" step (Step 3) -- rebuilt to match the latest design (new slack
design (6)/index.html): a 35-team incident-response catalog across 4
tiers (Mandatory/Recommended/Optional/External), tabbed, with only the
Mandatory tier required to continue. Custom team creation is gone in
this design -- the 35-team catalog replaces it.

No database yet for the assignment itself (still read back out of the
message on every click), but "who" is a real workspace member
(cards/slack_members_v2.py), not a mock name. Role/responsibility text
is always free-typed via a modal (cards/team_role_modal_v2.py) -- with
35 very different team types, a curated pick-list per team isn't
realistic, so this keeps every team fully functional without one.
"""

from .team_catalog_v2 import ALL_TEAMS, MANDATORY_TEAM_IDS, TIERS, TIER_EMOJI, find_team, teams_in_tier

ADD_CUSTOM_ROLE_VALUE = "__add_custom__"
ADD_CUSTOM_RESP_VALUE = "__add_custom_resp__"


def _short_team_name(name: str) -> str:
    """The real team names are long and get cut mid-word on a tab button
    ("...Detection..."). Most follow "Short Name (Detail)" or "Short Name
    / Detail" -- take just the short part for the tab label; the full
    name still shows in the team's own detail panel."""
    for sep in (" (", " / "):
        if sep in name:
            return name.split(sep)[0]
    return name

# Same role catalog as the design mockup -- a starting point offered for
# any team, since a curated list per team (35 very different team types)
# isn't realistic to maintain. "+ Type a role…" always covers anything
# not listed.
ROLE_CATALOG = [
    "IR Lead", "SOC Analyst", "Forensics Analyst", "Threat Hunter",
    "Identity & Access Owner", "Endpoint Owner", "Network Owner", "Legal Liaison",
]

# Sir's call: mapping a responsibility by hand for every single member is
# too much friction for an admin filling out 35 teams. Instead of a
# separate "map responsibilities" step, picking a role now auto-fills its
# one default test action immediately -- see v2_team_role_confirm in
# interactivity_v2.py. The old manual flow (_map_flow_blocks and friends)
# is left in place only as a fallback for a free-typed custom role, which
# has no default to draw from.
ROLE_DEFAULT_RESP = {
    "IR Lead": {
        "text": "Declare the incident and activate the response plan",
        "action": "Decide", "detail": "Confirm severity and formally activate the IR plan",
        "phase": "Initial Response",
    },
    "SOC Analyst": {
        "text": "Triage the first alert and declare severity",
        "action": "Decide", "detail": "Escalate to Sev-1 or stand down",
        "phase": "Initial Response",
    },
    "Forensics Analyst": {
        "text": "Preserve evidence and determine root cause",
        "action": "Decide", "detail": "Collect forensic images before remediation begins",
        "phase": "Containment",
    },
    "Threat Hunter": {
        "text": "Hunt for related indicators across the environment",
        "action": "Decide", "detail": "Scope any additional compromised assets",
        "phase": "Containment",
    },
    "Identity & Access Owner": {
        "text": "Lock down compromised accounts and credentials",
        "action": "Decide", "detail": "Force password resets and revoke active sessions",
        "phase": "Containment",
    },
    "Endpoint Owner": {
        "text": "Isolate affected endpoints from the network",
        "action": "Decide", "detail": "Choose isolate-VLAN vs quarantine-hosts",
        "phase": "Containment",
    },
    "Network Owner": {
        "text": "Block malicious traffic at the network perimeter",
        "action": "Decide", "detail": "Apply firewall / DNS blocks",
        "phase": "Containment",
    },
    "Legal Liaison": {
        "text": "Assess legal, regulatory and notification obligations",
        "action": "Decide", "detail": "Determine breach notification requirements",
        "phase": "Post-Incident",
    },
}

# (key, hint shown once picked) -- generic exercise action types, not tied to any one team.
ACTIONS = [
    ("Decide", "Makes a call under time pressure — timed from the moment the option is posted."),
    ("Execute", "Performs the recovery or containment step itself."),
    ("Verify", "Confirms a target was actually met — the evidence line."),
    ("Notify", "Briefs a named audience within a stated window."),
    ("Provide evidence", "Supplies a fact or artefact another team is blocked on."),
    ("Approve", "Signs off before the exercise can move on."),
]
ACTION_KEYS = [k for k, _ in ACTIONS]
ACTION_HINTS = dict(ACTIONS)

PHASES = ["Trigger", "Containment", "Comms", "Recovery", "Review"]


def _select_option(value: str, label: str) -> dict:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def read_current_state(message_blocks: list) -> dict:
    """
    {"teams": {team_id: [{"role","primary","backup"}, ...]},
     "resp": {team_id: [{"text","who","action","detail","phase"}, ...]},
     "add": {...}|None, "map": {...}|None, "active_tier": str, "expanded_team": str|None}
    """
    teams = {t["id"]: [] for t in ALL_TEAMS}
    resp = {t["id"]: [] for t in ALL_TEAMS}
    add = None
    map_state = None
    dm_open = set()
    active_tier = "Mandatory"
    expanded_team = None
    active_priority = None

    for block in message_blocks or []:
        block_id = block.get("block_id", "")

        if block_id.startswith("teamdmpreview|"):
            _, team_id, index = block_id.split("|", 2)
            dm_open.add(f"{team_id}:{index}")

        elif block_id.startswith("teamtier|"):
            active_tier = block_id.removeprefix("teamtier|")

        elif block_id.startswith("teamexpand|"):
            expanded_team = block_id.removeprefix("teamexpand|") or None

        elif block_id.startswith("teampriority|"):
            _, _team_id, priority = block_id.split("|", 2)
            active_priority = priority or None

        elif block_id.startswith("teamrolepick|"):
            _, team_id, role = block_id.split("|", 2)
            member = next((m for m in teams.setdefault(team_id, []) if m["role"] == role), None)
            for el in block.get("elements", []):
                option = el.get("initial_option")
                if not option:
                    continue
                value = option.get("value")
                if value in (None, "__none__"):
                    continue
                if member is None:
                    member = {"role": role, "primary": [], "backup": []}
                    teams[team_id].append(member)
                if el.get("action_id") == "v2_team_role_primary_select":
                    member["primary"] = [value]
                elif el.get("action_id") == "v2_team_role_backup_select":
                    member["backup"] = [value]

        elif block_id.startswith("teammember|"):
            _, team_id, role, primary_csv, backup_csv = block_id.split("|", 4)
            teams.setdefault(team_id, []).append(
                {
                    "role": role,
                    "primary": [c for c in primary_csv.split(",") if c],
                    "backup": [c for c in backup_csv.split(",") if c],
                }
            )

        elif block_id.startswith("teamaddrow_"):
            team_id = block_id.removeprefix("teamaddrow_")
            add = add or {"team_id": team_id, "role": None, "primary": [], "backup": []}
            for el in block.get("elements", []):
                option = el.get("initial_option")
                if not option:
                    continue
                value = option.get("value")
                if el.get("action_id") == "v2_team_role_select":
                    if value not in (None, "__none__", ADD_CUSTOM_ROLE_VALUE):
                        add["role"] = value
                elif el.get("action_id") == "v2_team_member_select":
                    if value not in (None, "__none__"):
                        add["primary"] = [value]
                elif el.get("action_id") == "v2_team_backup_select":
                    if value not in (None, "__none__"):
                        add["backup"] = [value]

        elif block_id.startswith("respmap|"):
            _, team_id, text, who, action, detail, phase = block_id.split("|", 6)
            resp.setdefault(team_id, []).append(
                {"text": text, "who": who, "action": action, "detail": detail, "phase": phase}
            )

        elif block_id.startswith("respform_resp_"):
            team_id = block_id.removeprefix("respform_resp_")
            map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            option = block.get("accessory", {}).get("initial_option")
            if option and option.get("value") not in (None, "__none__", ADD_CUSTOM_RESP_VALUE):
                map_state["text"] = option["value"]

        elif block_id.startswith("respform_who_"):
            team_id = block_id.removeprefix("respform_who_")
            map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            for el in block.get("elements", []):
                if el.get("style") == "primary":
                    map_state["who"] = el.get("value")

        elif block_id.startswith("respform_action_"):
            team_id = block_id.removeprefix("respform_action_")
            map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            for el in block.get("elements", []):
                if el.get("style") == "primary":
                    map_state["action"] = el.get("value")

        elif block_id.startswith("respform_detail_"):
            team_id = block_id.removeprefix("respform_detail_")
            map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            option = block.get("accessory", {}).get("initial_option")
            if option and option.get("value") not in (None, "__none__"):
                map_state["detail"] = option["value"]

        elif block_id.startswith("respform_phase_"):
            team_id = block_id.removeprefix("respform_phase_")
            map_state = map_state or {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            for el in block.get("elements", []):
                if el.get("style") == "primary":
                    map_state["phase"] = el.get("value")

    return {
        "teams": teams, "resp": resp, "add": add, "map": map_state,
        "dm_open": dm_open, "active_tier": active_tier, "expanded_team": expanded_team,
        "active_priority": active_priority,
    }


def _member_block(team_id: str, index: int, member: dict, by_code: dict, resp_mapped: list | None = None, dm_open: set | None = None) -> list:
    role = member["role"]
    primary_names = " & ".join(by_code[c]["n"] for c in member["primary"] if c in by_code)
    backup_names = ", ".join(by_code[c]["n"] for c in member["backup"] if c in by_code)
    text = f":white_check_mark: *{role}*\n{primary_names}  ·  _Notified_"
    if backup_names:
        text += f"\n:arrows_counterclockwise: Backup: {backup_names}"
    row = {
        "type": "section",
        "block_id": f"teammember|{team_id}|{role}|{','.join(member['primary'])}|{','.join(member['backup'])}",
        "text": {"type": "mrkdwn", "text": text},
        "accessory": {
            "type": "overflow",
            "action_id": "v2_team_member_overflow",
            "options": [
                {"text": {"type": "plain_text", "text": "✕ Remove"}, "value": f"{team_id}:{index}:remove"},
            ],
        },
    }
    blocks = [row]

    # Sir's call: an admin shouldn't have to click anything to see (or set)
    # the responsibility -- every catalog role's one default test action is
    # already auto-mapped the moment the member is added (see
    # v2_team_role_confirm), so just show it here directly, always, with
    # no toggle in the way.
    mine = [r for r in (resp_mapped or []) if r.get("who") == role]
    if mine:
        r = mine[0]
        blocks.append(
            {
                "type": "section",
                "block_id": f"teamresp|{team_id}|{index}",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Responsibility*\n{r['text']}\n\n"
                        f"*Action*\n{r['action']}: {r['detail']}\n\n"
                        f"*Test phase*\n{r.get('phase', '')}"
                    ),
                },
            }
        )
    return blocks


def _add_flow_blocks(team: dict, add: dict, people: list, by_code: dict) -> list:
    team_id = team["id"]
    role = add.get("role")
    primary = add.get("primary", [])
    backup = add.get("backup", [])

    # Real roles for THIS specific team (sir's IR Team Catalog spreadsheet)
    # -- each team has its own roles, not the same generic list reused
    # everywhere. Falls back to the old generic catalog only for a team
    # that somehow isn't in the spreadsheet yet.
    from .team_catalog_v2 import roles_for_team

    # A short letter tag instead of a color dot -- at this tiny dropdown
    # size, red vs orange circles look too similar to tell apart. Letters
    # (M/R/O) stay unambiguous no matter how small Slack renders them.
    priority_tag = {"Mandatory": "M", "Recommended": "R", "Optional": "O"}

    team_roles = roles_for_team(team_id)
    if team_roles:
        catalog_role_names = [r["role"] for r in team_roles]
        role_options = [
            _select_option(r["role"], f"[{priority_tag.get(r['priority'], '?')}] {r['role']}") for r in team_roles
        ]
    else:
        catalog_role_names = ROLE_CATALOG
        role_options = [_select_option(r, r) for r in ROLE_CATALOG]

    # A custom-typed role (from the modal) isn't in the catalog -- Slack
    # rejects an initial_option whose value isn't one of the listed
    # options, so add it as its own option when it's active.
    if role and role not in catalog_role_names:
        role_options.append(_select_option(role, role))
    role_options.append(_select_option(ADD_CUSTOM_ROLE_VALUE, "+ Type a role…"))

    role_accessory = {
        "type": "static_select",
        "action_id": "v2_team_role_select",
        "options": role_options,
    }
    if role:
        # Must match one listed option's text AND value exactly (Slack
        # rejects a mismatched initial_option) -- so reuse the option we
        # already built for this role rather than re-deriving its label.
        matching = next((o for o in role_options if o["value"] == role), None)
        role_accessory["initial_option"] = matching or _select_option(role, role)
    else:
        role_accessory["placeholder"] = {"type": "plain_text", "text": "Select a role…"}

    if not people:
        return [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_No one in this workspace to assign yet._"}]},
            {
                "type": "actions",
                "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Cancel", "emoji": True}, "action_id": "v2_team_add_cancel", "value": team_id}],
            },
        ]

    primary_id = primary[0] if primary else None
    backup_id = backup[0] if backup else None

    member_options = [{"text": {"type": "plain_text", "text": p["n"]}, "value": p["i"]} for p in people]
    member_accessory = {"type": "static_select", "action_id": "v2_team_member_select", "options": member_options}
    if primary_id and primary_id in by_code:
        member_accessory["initial_option"] = {"text": {"type": "plain_text", "text": by_code[primary_id]["n"]}, "value": primary_id}
    else:
        member_accessory["placeholder"] = {"type": "plain_text", "text": "Select member…"}

    # A person just made primary can't also be their own backup.
    backup_options_people = [p for p in people if p["i"] != primary_id]
    backup_options = [{"text": {"type": "plain_text", "text": p["n"]}, "value": p["i"]} for p in backup_options_people]
    backup_accessory = {"type": "static_select", "action_id": "v2_team_backup_select", "options": backup_options or [{"text": {"type": "plain_text", "text": "No one else available"}, "value": "__none__"}]}
    if backup_id and backup_id in by_code and backup_id != primary_id:
        backup_accessory["initial_option"] = {"text": {"type": "plain_text", "text": by_code[backup_id]["n"]}, "value": backup_id}
    else:
        backup_accessory["placeholder"] = {"type": "plain_text", "text": "Select backup member…"}

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "`[M]` *Mandatory*   ·   `[R]` *Recommended*   ·   `[O]` *Optional*"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "*Role*  ·  *Member*  ·  *Backup member*"}]},
        {
            "type": "actions",
            "block_id": f"teamaddrow_{team_id}",
            "elements": [role_accessory, member_accessory, backup_accessory],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_No role goes into a test with one person behind it — the backup is DM'd the same actions and steps in if the holder can't respond._"}
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Add member", "emoji": True},
                    "action_id": "v2_team_role_confirm",
                    "value": team_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "v2_team_add_cancel",
                    "value": team_id,
                },
            ],
        },
    ]
    return blocks


def _resp_map_entry_block(team_id: str, index: int, r: dict, by_code: dict) -> dict:
    who_name = by_code.get(r["who"], {}).get("n", r["who"])
    text = f":small_blue_diamond: *{r['text']}*\n:bust_in_silhouette: {who_name}  ·  → *{r['action']}:* {r['detail']}  ·  `{r['phase']}`"
    return {
        "type": "section",
        "block_id": f"respmap|{team_id}|{r['text']}|{r['who']}|{r['action']}|{r['detail']}|{r['phase']}",
        "text": {"type": "mrkdwn", "text": text},
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "✕", "emoji": True},
            "action_id": "v2_resp_map_remove",
            "value": f"{team_id}:{index}",
        },
    }


def _map_flow_blocks(team: dict, members: list, resp_mapped: list, map_state: dict, by_code: dict) -> list:
    team_id = team["id"]

    if not members:
        return [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Add a member first — every test action has to belong to someone._"}]}
        ]

    text = map_state.get("text")
    who = map_state.get("who")
    action = map_state.get("action")
    detail = map_state.get("detail")
    phase = map_state.get("phase") or "Containment"

    # No curated responsibility catalog either -- always free-typed.
    resp_options = []
    if text:
        resp_options.append(_select_option(text, text))
    resp_options.append(_select_option(ADD_CUSTOM_RESP_VALUE, "+ Type a responsibility…"))
    resp_accessory = {"type": "static_select", "action_id": "v2_resp_text_select", "options": resp_options}
    if text:
        resp_accessory["initial_option"] = _select_option(text, text)
    else:
        resp_accessory["placeholder"] = {"type": "plain_text", "text": "Select a responsibility…"}

    blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "*Responsibilities → what they do in a test*"}]},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Every responsibility maps to one exact action a named member performs during an exercise. That action is what gets timed and scored._"}]},
    ]
    for i, r in enumerate(resp_mapped):
        blocks.append(_resp_map_entry_block(team_id, i, r, by_code))

    # Every catalog role already gets its responsibility auto-mapped the
    # moment it's added (see v2_team_role_confirm) -- this manual form
    # below is only a fallback for a role that has none yet (e.g. a
    # free-typed custom role). Once every member already has a mapping,
    # skip straight to "Done mapping" instead of showing a confusing blank
    # form underneath an already-filled-in entry.
    mapped_roles = {r["who"] for r in resp_mapped}
    unmapped_roles = {m["role"] for m in members if m["role"] not in mapped_roles}
    if not unmapped_roles:
        blocks.append(
            {
                "type": "actions",
                "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Done mapping", "emoji": True}, "action_id": "v2_resp_map_done", "value": team_id}],
            }
        )
        return blocks

    blocks.append(
        {"type": "section", "block_id": f"respform_resp_{team_id}", "text": {"type": "mrkdwn", "text": "*Responsibility*"}, "accessory": resp_accessory}
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Performed by*"}]})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"respform_who_{team_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": m["role"], "emoji": True},
                    "action_id": f"v2_resp_who_toggle__{i}",
                    "value": (m["primary"][0] if m["primary"] else ""),
                    **({"style": "primary"} if m["primary"] and who == m["primary"][0] else {}),
                }
                for i, m in enumerate(members)
                if m["primary"]
            ],
        }
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Action in a test*"}]})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"respform_action_{team_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": k, "emoji": True},
                    "action_id": f"v2_resp_action_pick__{k.replace(' ', '_')}",
                    "value": k,
                    **({"style": "primary"} if action == k else {}),
                }
                for k in ACTION_KEYS
            ],
        }
    )
    if action:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{ACTION_HINTS[action]}_"}]})

    detail_options = []
    if detail and action:
        detail_options.append(_select_option(detail, detail))
    if action:
        detail_options.append(_select_option("__add_custom_detail__", "+ Type the exact action…"))
    detail_accessory = {"type": "static_select", "action_id": "v2_resp_detail_select", "options": detail_options or [_select_option("__none__", "Pick an action type first…")]}
    if detail and action:
        detail_accessory["initial_option"] = _select_option(detail, detail)
    else:
        detail_accessory["placeholder"] = {
            "type": "plain_text",
            "text": "Select what they actually do…" if action else "Pick an action type first…",
        }
    blocks.append(
        {"type": "section", "block_id": f"respform_detail_{team_id}", "text": {"type": "mrkdwn", "text": "*The exact action*"}, "accessory": detail_accessory}
    )

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*When in the test*"}]})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"respform_phase_{team_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": p, "emoji": True},
                    "action_id": f"v2_resp_phase_pick__{p}",
                    "value": p,
                    **({"style": "primary"} if phase == p else {}),
                }
                for p in PHASES
            ],
        }
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Map to test action", "emoji": True},
                    "action_id": "v2_resp_map_confirm",
                    "value": team_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done mapping", "emoji": True},
                    "action_id": "v2_resp_map_done",
                    "value": team_id,
                },
            ],
        }
    )
    return blocks


_TIER_TONE_EMOJI = {"Mandatory": ":red_circle:", "Recommended": ":large_orange_circle:", "Optional": ":large_green_circle:", "External": ":white_circle:"}
_PRIORITY_TAG = {"Mandatory": "M", "Recommended": "R", "Optional": "O"}


def _team_is_staffed(team_id: str, members: list) -> bool:
    """
    A team counts as staffed once every one of ITS Mandatory-priority
    catalog roles has both a primary and a backup -- not just "has one
    member added", which used to let a team with only one of several
    mandatory roles filled count as done. Falls back to "at least one
    fully-filled role" for a team with no catalog entry yet.
    """
    from .team_catalog_v2 import roles_for_team

    mandatory_roles = {r["role"] for r in roles_for_team(team_id) if r["priority"] == "Mandatory"}
    filled_roles = {m["role"] for m in members if m.get("primary") and m.get("backup")}
    if mandatory_roles:
        return mandatory_roles.issubset(filled_roles)
    return bool(filled_roles)


def _info_fields_block(team: dict) -> list:
    return [
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Purpose*\n{team['purpose']}"},
                {"type": "mrkdwn", "text": f"*Primary IR phases*\n{team['phases']}"},
                {"type": "mrkdwn", "text": f"*Team type*\n{team['type']}"},
                {"type": "mrkdwn", "text": f"*Can be outsourced*\n{team['outsource']}"},
            ],
        }
    ]


def _role_row_blocks(team_id: str, role_entry: dict, members: list, people: list, by_code: dict) -> list:
    role = role_entry["role"]
    priority = role_entry["priority"]
    existing = next((m for m in members if m["role"] == role), None)
    primary_id = existing["primary"][0] if existing and existing.get("primary") else None
    backup_id = existing["backup"][0] if existing and existing.get("backup") else None

    if primary_id and backup_id:
        status = ":white_check_mark: Done"
    elif primary_id:
        status = ":large_blue_circle: Primary set — needs a backup"
    else:
        status = ":hourglass_flowing_sand: Pending"

    role_header = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{role}*\n{status}"},
    }
    if primary_id or backup_id:
        # A labeled button with a confirm dialog instead of an unlabeled
        # "⋮" overflow menu -- the overflow icon gave no hint it meant
        # "remove" until clicked, and had no undo-safety net.
        role_header["accessory"] = {
            "type": "button",
            "text": {"type": "plain_text", "text": "✕ Remove", "emoji": True},
            "action_id": "v2_team_role_remove",
            "value": f"{team_id}|{role}",
            "style": "danger",
            "confirm": {
                "title": {"type": "plain_text", "text": "Remove this assignment?"},
                "text": {"type": "mrkdwn", "text": f"This clears Primary and Backup for *{role}*. You'll need to reassign both."},
                "confirm": {"type": "plain_text", "text": "Remove"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }

    blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "`ROLE`"}]},
        role_header,
    ]

    member_options = [{"text": {"type": "plain_text", "text": p["n"]}, "value": p["i"]} for p in people]
    if not member_options:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No one in this workspace to assign yet._"}]})
        return blocks

    primary_accessory = {
        "type": "static_select",
        "action_id": "v2_team_role_primary_select",
        "options": member_options,
        "placeholder": {"type": "plain_text", "text": "Primary member…"},
    }
    if primary_id and primary_id in by_code:
        primary_accessory["initial_option"] = {"text": {"type": "plain_text", "text": by_code[primary_id]["n"]}, "value": primary_id}

    backup_candidates = [p for p in people if p["i"] != primary_id]
    backup_options = [{"text": {"type": "plain_text", "text": p["n"]}, "value": p["i"]} for p in backup_candidates] or [
        {"text": {"type": "plain_text", "text": "No one else available"}, "value": "__none__"}
    ]
    backup_accessory = {
        "type": "static_select",
        "action_id": "v2_team_role_backup_select",
        "options": backup_options,
        "placeholder": {"type": "plain_text", "text": "Backup member…"},
    }
    if backup_id and backup_id in by_code and backup_id != primary_id:
        backup_accessory["initial_option"] = {"text": {"type": "plain_text", "text": by_code[backup_id]["n"]}, "value": backup_id}

    blocks.append(
        {
            "type": "actions",
            "block_id": f"teamrolepick|{team_id}|{role}",
            "elements": [primary_accessory, backup_accessory],
        }
    )
    return blocks


def _team_block(team: dict, members: list, resp_mapped: list, add: dict | None, map_state: dict | None, people: list, by_code: dict, expanded: bool, dm_open: set | None = None, active_priority: str | None = None) -> list:
    """Full detail panel for the one team currently selected via the team
    tab row (build_teams_card only ever calls this for that one team)."""
    from .team_catalog_v2 import roles_for_team

    team_id = team["id"]
    is_done = _team_is_staffed(team_id, members)
    status_text = ":white_check_mark: *Complete*" if is_done else ":hourglass_flowing_sand: *Pending*"

    blocks = [
        {
            "type": "section",
            "block_id": f"teamheader|{team_id}",
            "text": {"type": "mrkdwn", "text": f"*{team_id} · {team['name']}*\n`{team['tier']}`  ·  `{team['type']}`"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": status_text}},
        *_info_fields_block(team),
    ]

    catalog = roles_for_team(team_id)
    if catalog:
        present_priorities = [p for p in ("Mandatory", "Recommended", "Optional") if any(r["priority"] == p for r in catalog)]
        if active_priority not in present_priorities:
            active_priority = present_priorities[0] if present_priorities else None

        if len(present_priorities) > 1:
            blocks.append(
                {
                    "type": "actions",
                    "block_id": f"teampriority|{team_id}|{active_priority or ''}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": f"{p} roles ({sum(1 for r in catalog if r['priority'] == p)})", "emoji": True},
                            "action_id": f"v2_team_priority_tab__{team_id}__{p}",
                            "value": p,
                            **({"style": "primary"} if p == active_priority else {}),
                        }
                        for p in present_priorities
                    ],
                }
            )

        blocks.append({"type": "divider"})
        for role_entry in [r for r in catalog if r["priority"] == active_priority]:
            blocks.extend(_role_row_blocks(team_id, role_entry, members, people, by_code))
            blocks.append({"type": "divider"})

    # Any member not in the catalog (free-typed custom role) -- shown
    # below the catalog table, same as before.
    catalog_role_names = {r["role"] for r in catalog}
    custom_members = [(i, m) for i, m in enumerate(members) if m["role"] not in catalog_role_names]
    if custom_members:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Custom roles*"}]})
        for i, member in custom_members:
            blocks.extend(_member_block(team_id, i, member, by_code, resp_mapped, dm_open))
        blocks.append({"type": "divider"})

    is_adding = add and add.get("team_id") == team_id
    is_mapping = map_state and map_state.get("team_id") == team_id

    if is_mapping:
        blocks.extend(_map_flow_blocks(team, members, resp_mapped, map_state, by_code))
        blocks.append({"type": "divider"})
    elif is_adding:
        blocks.extend(_add_flow_blocks(team, add, people, by_code))
        blocks.append({"type": "divider"})

    # Sir's call: for a small company, the same 2-3 people run every team
    # -- once this team's Role/Member/Backup is filled, let the admin copy
    # the exact same assignment onto sibling teams instead of re-entering
    # it per team. A modal (not inline checkboxes) -- a plain message has
    # no reliable way to carry a checkbox's checked state between one
    # click and the next, a modal's submission does.
    if members:
        siblings = [t for t in ALL_TEAMS if t["tier"] == team["tier"] and t["id"] != team_id]
        if siblings:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": ":twisted_rightwards_arrows: Apply same user to other teams", "emoji": True},
                            "action_id": "v2_team_copy_open",
                            "value": team_id,
                        }
                    ],
                }
            )

    return blocks


def build_teams_card(state: dict, people: list) -> dict:
    teams = state.get("teams", {})
    resp = state.get("resp", {})
    add = state.get("add")
    map_state = state.get("map")
    dm_open = state.get("dm_open", set())
    active_tier = state.get("active_tier") or "Mandatory"
    expanded_team = state.get("expanded_team")
    active_priority = state.get("active_priority")
    by_code = {p["i"]: p for p in people}

    staffed = sum(1 for tid in MANDATORY_TEAM_IDS if _team_is_staffed(tid, teams.get(tid, [])))
    total = len(MANDATORY_TEAM_IDS)
    total_members = sum(len(m) for m in teams.values())
    total_mapped = sum(len(r) for r in resp.values())
    ready = staffed == total

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":shield: Step 2 · Response teams", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":large_green_circle: *{staffed} / {total} mandatory staffed*"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Assign members to IR teams from the TestMyPlan catalog. Mandatory teams must be staffed before you can continue.",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: *Complete*   ·   :hourglass_flowing_sand: *Pending*"}},
        {
            "type": "actions",
            "block_id": f"teamtier|{active_tier}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"{TIER_EMOJI[tier]} {tier} ({len(teams_in_tier(tier))})", "emoji": True},
                    "action_id": f"v2_team_tier__{tier}",
                    "value": tier,
                    **({"style": "primary"} if tier == active_tier else {}),
                }
                for tier in TIERS
            ],
        },
    ]

    blocks.append({"type": "divider"})

    # "Select a category, then a team" -- one tab row per team in the
    # active tier (instead of a list of rows each with its own Open
    # button), with only the selected team's full detail shown below.
    tier_teams = teams_in_tier(active_tier)
    if not any(t["id"] == expanded_team for t in tier_teams):
        expanded_team = tier_teams[0]["id"] if tier_teams else None

    if tier_teams:
        tier_staffed = sum(1 for t in tier_teams if _team_is_staffed(t["id"], teams.get(t["id"], [])))
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*{active_tier} tier:* {tier_staffed} / {len(tier_teams)} staffed"}],
            }
        )

        # Jump straight to any team across every tier -- with 35 teams
        # total, clicking through tabs tier by tier to find one specific
        # team is slow.
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "static_select",
                        "action_id": "v2_team_jump_select",
                        "placeholder": {"type": "plain_text", "text": "Jump to a team…"},
                        "options": [
                            {"text": {"type": "plain_text", "text": f"{t['id']} · {_short_team_name(t['name'])}"[:75]}, "value": t["id"]}
                            for t in ALL_TEAMS
                        ],
                    }
                ],
            }
        )

        team_tab_elements = [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": f"{':white_check_mark:' if _team_is_staffed(t['id'], teams.get(t['id'], [])) else ':hourglass_flowing_sand:'} {_short_team_name(t['name'])}"[:75],
                    "emoji": True,
                },
                "action_id": f"v2_team_expand_toggle__{t['id']}",
                "value": t["id"],
                **({"style": "primary"} if t["id"] == expanded_team else {}),
            }
            for t in tier_teams
        ]
        blocks.append({"type": "actions", "block_id": f"teamexpand|{expanded_team or ''}", "elements": team_tab_elements})
        blocks.append({"type": "divider"})

    selected_team = next((t for t in tier_teams if t["id"] == expanded_team), None)
    if selected_team:
        blocks.extend(
            _team_block(
                selected_team, teams.get(selected_team["id"], []), resp.get(selected_team["id"], []), add, map_state,
                people, by_code, True, dm_open, active_priority,
            )
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "→ Continue — review my threats" if ready else f"Continue ({staffed}/{total} staffed)",
                        "emoji": True,
                    },
                    "action_id": "v2_teams_done",
                    "value": "next",
                    **({"style": "primary"} if ready else {}),
                }
            ],
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"{total_members} member(s) added · {total_mapped} responsibilit{'y' if total_mapped == 1 else 'ies'} mapped."}
            ],
        }
    )

    return {"blocks": blocks}


def build_teams_done_card() -> dict:
    """Short confirmation shown right after Configure Teams finishes, so
    the admin knows what's next before the card jumps straight into
    Threat Profile -- sir's call."""
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":tada: Teams configured", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Every mandatory team has its roles staffed — you're ready to move on.",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":white_check_mark:  *Configure Teams* — _done_"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":arrow_right:  *Threat Profile* — up next"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":clipboard:  *Plan* — after that"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "→ Continue to Threat Profile", "emoji": True},
                        "action_id": "v2_teams_confirm_continue",
                        "value": "next",
                        "style": "primary",
                    }
                ],
            },
        ]
    }
