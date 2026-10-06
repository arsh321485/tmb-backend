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

    for block in message_blocks or []:
        block_id = block.get("block_id", "")

        if block_id.startswith("teamdmpreview|"):
            _, team_id, index = block_id.split("|", 2)
            dm_open.add(f"{team_id}:{index}")

        elif block_id.startswith("teamtier|"):
            active_tier = block_id.removeprefix("teamtier|")

        elif block_id.startswith("teamexpand|"):
            expanded_team = block_id.removeprefix("teamexpand|") or None

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


def _team_block(team: dict, members: list, resp_mapped: list, add: dict | None, map_state: dict | None, people: list, by_code: dict, expanded: bool, dm_open: set | None = None) -> list:
    team_id = team["id"]
    tag = f"{len(members)} member{'s' if len(members) != 1 else ''}" if members else ("Mandatory" if team["tier"] == "Mandatory" else team["tier"])
    # Status is just the leading icon now -- no separate "Completed"/"Pending"
    # text pill, too many stacked labels looked cluttered.
    check = ":white_check_mark: " if members else ":hourglass_flowing_sand: "

    header = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"{check}*{team['id']} · {team['name']}*\n{team['tier']}  ·  `{tag}`  ·  `{team['type']}`"},
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "Hide" if expanded else "Open", "emoji": True},
            "action_id": "v2_team_expand_toggle",
            "value": "__none__" if expanded else team_id,
        },
    }
    blocks = [header]

    if not expanded:
        return blocks

    blocks.append(
        {
            "type": "section",
            "block_id": f"teamexpand|{team_id}",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Purpose*\n{team['purpose']}\n\n"
                    f"*Primary IR phases*\n{team['phases']}\n\n"
                    f"*Team type*\n{team['type']}\n\n"
                    f"*Can be outsourced*\n{team['outsource']}"
                ),
            },
        }
    )

    if not members:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_No members yet — add the people who will run this team in a test._"}]}
        )
    for i, member in enumerate(members):
        blocks.extend(_member_block(team_id, i, member, by_code, resp_mapped, dm_open))

    is_mapping = map_state and map_state.get("team_id") == team_id

    if is_mapping:
        blocks.extend(_map_flow_blocks(team, members, resp_mapped, map_state, by_code))
        blocks.append({"type": "divider"})
    else:
        # Sir's call: show the Role/Member/Backup form the instant the team
        # is expanded -- no "+ Assign member" click needed first. If there's
        # no in-progress pick for this team yet, start from a blank one.
        effective_add = add if (add and add.get("team_id") == team_id) else {"team_id": team_id, "role": None, "primary": [], "backup": []}
        blocks.extend(_add_flow_blocks(team, effective_add, people, by_code))
    blocks.append({"type": "divider"})
    return blocks


def build_teams_card(state: dict, people: list) -> dict:
    teams = state.get("teams", {})
    resp = state.get("resp", {})
    add = state.get("add")
    map_state = state.get("map")
    dm_open = state.get("dm_open", set())
    active_tier = state.get("active_tier") or "Mandatory"
    expanded_team = state.get("expanded_team")
    by_code = {p["i"]: p for p in people}

    staffed = sum(1 for tid in MANDATORY_TEAM_IDS if teams.get(tid))
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

    for team in teams_in_tier(active_tier):
        blocks.extend(
            _team_block(
                team, teams.get(team["id"], []), resp.get(team["id"], []), add, map_state,
                people, by_code, expanded_team == team["id"], dm_open,
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
                        "text": "→ Continue — review my threats" if ready else f"Staff all mandatory teams to continue ({staffed}/{total})",
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
