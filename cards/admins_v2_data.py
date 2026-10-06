"""
Shared data + card-building for the new-design preview's "Module admins"
step (Step 2, cards/interactivity_v2.py). No database yet for the
assignment itself (still read back out of the message on every click,
same as before) -- but "who" is now a real workspace member
(cards/slack_members_v2.py), not a mock name.
"""

MODULE_ADMINS = [
    {"id": "cyber", "m": "Cybersecurity", "note": "Owns the threat map, IR drills and containment scoring"},
    {"id": "privacy", "m": "Privacy", "note": "Owns the 72-hour clock and regulator evidence"},
]


def _select_option(value: str, label: str) -> dict:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def read_current_state(message_blocks: list) -> dict:
    """
    Reconstructs {"assigned": {module_id: slack_user_id}, "expanded": module_id|None}
    from the message Slack just sent us.
    """
    assigned = {}
    expanded = None

    for block in message_blocks or []:
        block_id = block.get("block_id", "")
        if block_id.startswith("admin_") and "__" in block_id:
            prefix, code = block_id.split("__", 1)
            mod_id = prefix.removeprefix("admin_")
            if code != "unset":
                assigned[mod_id] = code
        elif block_id.startswith("adminexpand_"):
            expanded = block_id.removeprefix("adminexpand_")

    return {"assigned": assigned, "expanded": expanded}


def _admin_row(mod: dict, assigned_code: str | None, expanded: str | None, people: list, by_code: dict, current_user_id: str) -> list:
    mod_id = mod["id"]
    blocks = []

    if assigned_code:
        if assigned_code.startswith("invited:"):
            # Recorded via "Invite by email" -- not a real Slack member
            # yet, so there's no one to DM. Honest label: the admin still
            # has to invite them into Slack themselves (a bot can't send
            # workspace invites -- confirmed live, "not_allowed_token_type").
            name, _, email = assigned_code.removeprefix("invited:").partition("|")
            person_label = name + (f" ({email})" if email else "")
            note = "Invited by email · add them to Slack, then Change to assign for real"
        else:
            person = by_code.get(assigned_code)
            person_label = person["n"] if person else f"<@{assigned_code}>"
            note = "You" if assigned_code == current_user_id else "Notified via DM"
        blocks.append(
            {
                "type": "section",
                "block_id": f"admin_{mod_id}__{assigned_code}",
                "text": {"type": "mrkdwn", "text": f":white_check_mark: *{mod['m']}*\n{person_label} · _{note}_"},
                "accessory": {
                    "type": "overflow",
                    "action_id": "v2_admin_overflow",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Change"}, "value": f"{mod_id}:change"},
                        {"text": {"type": "plain_text", "text": "Remove"}, "value": f"{mod_id}:remove"},
                    ],
                },
            }
        )
        return blocks

    blocks.append(
        {
            "type": "section",
            "block_id": f"admin_{mod_id}__unset",
            "text": {"type": "mrkdwn", "text": f"*{mod['m']}*\n{mod['note']}"},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Assign", "emoji": True},
                "action_id": "v2_admin_assign_open",
                "value": mod_id,
            },
        }
    )

    if expanded == mod_id:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*Who runs {mod['m']}?*"}],
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":bust_in_silhouette: Myself", "emoji": True},
                        "action_id": "v2_admin_pick_self",
                        "value": mod_id,
                    }
                ],
            }
        )
        # Clicking a person directly assigns them -- no separate confirm
        # step. Mistakes are fixed via the "..." Change option on the
        # confirmed row, which reopens this same picker.
        others = [p for p in people if p["i"] != current_user_id]
        if others:
            blocks.append(
                {
                    "type": "actions",
                    "block_id": f"adminexpand_{mod_id}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": p["n"].split()[0], "emoji": True},
                            # Unique per button -- Slack rejects multiple
                            # elements in the same block sharing one action_id
                            # (confirmed live: this exact bug just froze the
                            # picker instead of opening).
                            "action_id": f"v2_admin_pick_person__{p['i']}",
                            "value": f"{mod_id}:{p['i']}",
                        }
                        for p in others
                    ],
                }
            )
        else:
            blocks.append(
                {"type": "context", "elements": [{"type": "mrkdwn", "text": "_No one else in this workspace yet to delegate to._"}]}
            )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":email: Invite by email", "emoji": True},
                        "action_id": "v2_admin_invite_email",
                        "value": mod_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                        "action_id": "v2_admin_cancel",
                        "value": mod_id,
                    },
                ],
            }
        )

    return blocks


def build_admins_card(state: dict, people: list, current_user_id: str) -> dict:
    assigned = state.get("assigned", {})
    expanded = state.get("expanded")
    by_code = {p["i"]: p for p in people}

    n_set = len(assigned)
    total = len(MODULE_ADMINS)
    all_set = n_set == total

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":busts_in_silhouette: Step 1 · Module admins", "emoji": True}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":large_green_circle: *{n_set} / {total} set*"}],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Your confirmed threats span {total} modules, and each one needs an admin who owns "
                    "its plans and tests. Take a module yourself, or hand it to a colleague — you stay the "
                    "account owner either way."
                ),
            },
        },
    ]

    if not all_set:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "I'll run every module myself", "emoji": True},
                        "action_id": "v2_admin_take_all",
                        "value": "all",
                    }
                ],
            }
        )

    blocks.append({"type": "divider"})
    for mod in MODULE_ADMINS:
        blocks.extend(_admin_row(mod, assigned.get(mod["id"]), expanded, people, by_code, current_user_id))
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "→ Continue — set up response teams", "emoji": True},
                    "action_id": "v2_admins_done",
                    "value": "next",
                    **({"style": "primary"} if all_set else {}),
                }
            ],
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "One person can hold every module. Admins can be changed at any time from this channel."}
            ],
        }
    )

    return {"blocks": blocks}
