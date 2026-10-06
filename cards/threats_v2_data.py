"""
Shared data + card-building for the new-design preview's "Organizational
threats" step (cards/blocks_v2/02-org-threats.json). Kept as code (not
just static JSON) so the criticality dropdown, and the "+ Add a threat
we missed" inline form, can actually respond -- matches the same
taxonomy as the new design mockup (new slack design/js/data.js).

No database involved -- this is still a design-review demo, not real
backend logic. All current state (each threat's criticality, any
custom threats added, whether the add-threat form is open and what's
picked in it) is read back out of the message Slack sends us on every
click (payload["message"]["blocks"]), not stored anywhere -- good
enough for a click-through demo, and avoids building real persistence
before sir has approved the design at all.
"""

THREATS = [
    {
        "key": "ext", "module": "Cybersecurity", "icon": ":shield:",
        "label": "External attacker", "incidents": 2,
        "why": "Healthcare is the most-targeted ransomware sector, and your clinical systems run on a cloud EHR with a third-party claims processor attached.",
        "default_crit": "Critical",
    },
    {
        "key": "ins", "module": "Cybersecurity", "icon": ":shield:",
        "label": "Insider", "incidents": 1,
        "why": "4,200 staff with broad access to patient records — leaver and negligent-sharing exposure scales with headcount.",
        "default_crit": "High",
    },
    {
        "key": "breach", "module": "Privacy", "icon": ":lock:",
        "label": "Personal-data breach", "incidents": 2,
        "why": "Special-category health data under GDPR: a single misconfigured export is notifiable within 72 hours.",
        "default_crit": "Critical",
    },
    {
        "key": "rights", "module": "Privacy", "icon": ":lock:",
        "label": "Data-subject rights", "incidents": 1,
        "why": "Patient-facing services at this scale attract coordinated subject-access campaigns.",
        "default_crit": "Med",
    },
]

MODULES = ["Cybersecurity", "Privacy"]

# Threats an admin can add if the generated profile missed something --
# same catalog as the mockup (new slack design/js/data.js's extraThreats).
EXTRA_THREATS = {
    "Cybersecurity": ["Supply-chain compromise", "Denial of service", "Nation-state intrusion", "OT / medical-device attack"],
    "Privacy": ["Cross-border transfer failure", "Consent & lawful-basis failure", "Retention breach"],
}

CRIT_OPTIONS = ["Critical", "High", "Med", "Dropped"]
CRIT_EMOJI = {"Critical": "🔴", "High": "🟠", "Med": "🟡", "Dropped": "⚪"}
ADD_CRIT_CHOICES = ["Critical", "High", "Med"]  # a newly added threat can't start "Dropped"


def _select_option(value: str) -> dict:
    return {"text": {"type": "plain_text", "text": value}, "value": value}


def _threat_block(block_id: str, label: str, module: str, incidents, why: str, current_crit: str) -> dict:
    emoji = CRIT_EMOJI[current_crit]
    body = "_Dropped — won't be part of this test._" if current_crit == "Dropped" else f"_{why}_"
    return {
        "type": "section",
        "block_id": block_id,
        "text": {
            "type": "mrkdwn",
            "text": f"{emoji} *{label}* — {current_crit}\n{body}",
        },
    }


def read_current_state(message_blocks: list) -> dict:
    """
    Reconstructs {"fixed": {key: crit}, "custom": [...], "form": {...}|None}
    from the message Slack just sent us.
    """
    message_blocks = message_blocks or []
    fixed = {}
    custom = []
    form = None
    active_module = MODULES[0]
    active_crit = None
    active_threat = None
    active_incident = None

    for block in message_blocks:
        block_id = block.get("block_id", "")

        if block_id.startswith("threatmodule|"):
            active_module = block_id.removeprefix("threatmodule|")

        elif block_id.startswith("threatcrit|"):
            active_crit = block_id.removeprefix("threatcrit|")

        elif block_id.startswith("threattab|"):
            active_threat = block_id.removeprefix("threattab|")

        elif block_id.startswith("threatinc|"):
            active_incident = block_id.removeprefix("threatinc|")

        elif block_id.startswith("threat_"):
            key = block_id.removeprefix("threat_")
            option = block.get("accessory", {}).get("initial_option", {})
            fixed[key] = option.get("value", "")

        elif block_id.startswith("customthreat|"):
            _, module, label = block_id.split("|", 2)
            option = block.get("accessory", {}).get("initial_option", {})
            custom.append({"module": module, "label": label, "crit": option.get("value", "")})

        elif block_id == "add_form_module":
            option = block.get("accessory", {}).get("initial_option") or {}
            form = form or {}
            form["module"] = option.get("value", MODULES[0])

        elif block_id == "add_form_threat":
            option = block.get("accessory", {}).get("initial_option") or {}
            form = form or {}
            form["threat"] = option.get("value", "")

        elif block_id == "add_form_crit":
            form = form or {}
            chosen = None
            for el in block.get("elements", []):
                if el.get("style") == "primary":
                    chosen = el.get("value")
            form["crit"] = chosen

    return {
        "fixed": fixed, "custom": custom, "form": form, "active_module": active_module,
        "active_crit": active_crit, "active_threat": active_threat, "active_incident": active_incident,
    }


def _add_form_blocks(form: dict, custom: list) -> list:
    module = form.get("module") or MODULES[0]
    threat = form.get("threat")
    crit = form.get("crit")
    # Same as the mockup (flow-cards.jsx line 154): don't offer a threat
    # that's already been added for this module -- no duplicates.
    already_added = {c["label"] for c in custom if c["module"] == module}
    threat_options = [t for t in EXTRA_THREATS.get(module, []) if t not in already_added]

    blocks = [
        {"type": "divider"},
        {
            "type": "section",
            "block_id": "add_form_module",
            "text": {"type": "mrkdwn", "text": "*Module*"},
            "accessory": {
                "type": "static_select",
                "action_id": "v2_threat_add_module_select",
                "initial_option": _select_option(module),
                "options": [_select_option(m) for m in MODULES],
            },
        },
        {
            "type": "section",
            "block_id": "add_form_threat",
            "text": {"type": "mrkdwn", "text": "*Threat*"},
            "accessory": {
                "type": "static_select",
                "action_id": "v2_threat_add_threat_select",
                "initial_option": _select_option(threat) if threat else {
                    "text": {"type": "plain_text", "text": "Select a threat…"}, "value": "__none__"
                },
                "options": (
                    [{"text": {"type": "plain_text", "text": "Select a threat…"}, "value": "__none__"}]
                    if not threat else []
                ) + [_select_option(t) for t in threat_options],
            },
        },
        {
            "type": "actions",
            "block_id": "add_form_crit",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": c, "emoji": True},
                    "action_id": f"v2_threat_add_crit__{c}",
                    "value": c,
                    **({"style": "primary"} if c == crit else {}),
                }
                for c in ADD_CRIT_CHOICES
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "+ Add threat", "emoji": True},
                    "action_id": "v2_threat_add_confirm",
                    "value": "confirm",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "v2_threat_add_cancel",
                    "value": "cancel",
                },
            ],
        },
    ]
    return blocks


def build_org_threats_card(state: dict, profile: dict | None = None) -> dict:
    """
    state: {"fixed": {key: crit}, "custom": [{"module","label","crit"}],
    "form": {"module","threat","crit"} | None}.

    profile: the real Organization Details answers (Step "Organization
    Details") -- shown as context tags at the top so it's clear these
    threats were generated FROM what the admin just entered, not from a
    fixed mockup company. Workforce size / tech estate aren't collected
    yet (no fields for them on that step), so those tags are omitted
    until that's added rather than showing fake placeholder numbers.
    """
    fixed_state = state.get("fixed", {})
    custom = state.get("custom", [])
    form = state.get("form")

    fixed_kept = [t for t in THREATS if fixed_state.get(t["key"], t["default_crit"]) != "Dropped"]
    custom_kept = [c for c in custom if c["crit"] != "Dropped"]
    total_kept = len(fixed_kept) + len(custom_kept)

    counts = {"Critical": 0, "High": 0, "Med": 0, "Dropped": 0}
    for t in THREATS:
        counts[fixed_state.get(t["key"], t["default_crit"])] += 1
    for c in custom:
        counts[c["crit"]] += 1

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":dart: Step 3 · Organizational threats", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f":red_circle: *{total_kept} threats*"}
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f":red_circle: *{counts['Critical']}* Critical   |   "
                        f":large_orange_circle: *{counts['High']}* High   |   "
                        f":large_yellow_circle: *{counts['Med']}* Med   |   "
                        f"⚪ *{counts['Dropped']}* Dropped"
                    ),
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ">Generated from what you told us at sign-up — nothing to fill in, and it comes first: the threats decide "
                    "which modules you need admins and teams for. Drop anything that doesn't apply, or change a criticality."
                ),
            },
        },
    ]

    if profile and (profile.get("industry") or profile.get("regions") or profile.get("regulations")):
        tags = []
        if profile.get("industry"):
            tags.append(f"*SECTOR*  {profile['industry']}")
        if profile.get("regions"):
            tags.append(f"*REGIONS*  {' · '.join(profile['regions'])}")
        if profile.get("regulations"):
            tags.append(f"*REGULATION*  {' · '.join(profile['regulations'])}")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "   ".join(tags)}]})

    active_module = state.get("active_module") or MODULES[0]
    module_icon = {"Cybersecurity": ":shield:", "Privacy": ":lock:"}

    # Sub-tabs like the Teams card's tier tabs -- one module shown at a
    # time instead of both stacked, each tab labeled with its own kept count.
    blocks.append({"type": "divider"})
    tab_elements = []
    for module in MODULES:
        mod_fixed = [t for t in THREATS if t["module"] == module]
        mod_custom = [c for c in custom if c["module"] == module]
        mod_kept = len([t for t in mod_fixed if fixed_state.get(t["key"], t["default_crit"]) != "Dropped"]) + \
            len([c for c in mod_custom if c["crit"] != "Dropped"])
        tab_elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{module_icon.get(module, '')} {module} ({mod_kept})", "emoji": True},
                "action_id": f"v2_threat_module_tab__{module}",
                "value": module,
                **({"style": "primary"} if module == active_module else {}),
            }
        )
    blocks.append({"type": "actions", "block_id": f"threatmodule|{active_module}", "elements": tab_elements})
    blocks.append({"type": "divider"})

    # All threats (fixed + custom) for the active module, each carrying
    # its own effective criticality -- drives both the criticality tab row
    # and the threat-name tab row below it.
    mod_fixed = [t for t in THREATS if t["module"] == active_module]
    mod_custom_list = [c for c in custom if c["module"] == active_module]
    mod_items = [
        {"key": t["key"], "label": t["label"], "crit": fixed_state.get(t["key"], t["default_crit"]), "custom": False, "why": t["why"]}
        for t in mod_fixed
    ] + [
        {"key": f"custom:{c['label']}", "label": c["label"], "crit": c["crit"], "custom": True, "why": "Added by you — no scenarios generated yet."}
        for c in mod_custom_list
    ]

    # Criticality tabs -- only ones that actually have a threat in them,
    # so there's never a dead empty tab to click into.
    present_crits = [c for c in CRIT_OPTIONS if any(i["crit"] == c for i in mod_items)]
    active_crit = state.get("active_crit")
    if active_crit not in present_crits:
        active_crit = present_crits[0] if present_crits else None

    if present_crits:
        crit_tab_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{CRIT_EMOJI[c]} {c} ({sum(1 for i in mod_items if i['crit'] == c)})", "emoji": True},
                "action_id": f"v2_threat_crit_tab__{c}",
                "value": c,
                **({"style": "primary"} if c == active_crit else {}),
            }
            for c in present_crits
        ]
        blocks.append({"type": "actions", "block_id": f"threatcrit|{active_crit}", "elements": crit_tab_elements})

    items_in_crit = [i for i in mod_items if i["crit"] == active_crit] if active_crit else []

    # Threat-name tabs -- "External attacker" / "Insider" etc, side by
    # side instead of stacked. Selecting one shows its details right away
    # below, no extra "Open" click.
    active_threat = state.get("active_threat")
    if not any(i["key"] == active_threat for i in items_in_crit):
        active_threat = items_in_crit[0]["key"] if items_in_crit else None

    if items_in_crit:
        threat_tab_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": i["label"], "emoji": True},
                "action_id": f"v2_threat_name_tab__{i['key']}",
                "value": i["key"],
                **({"style": "primary"} if i["key"] == active_threat else {}),
            }
            for i in items_in_crit
        ]
        blocks.append({"type": "actions", "block_id": f"threattab|{active_threat}", "elements": threat_tab_elements})

    active_item = next((i for i in items_in_crit if i["key"] == active_threat), None)
    if active_item:
        if active_item["crit"] == "Dropped":
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":large_blue_diamond: `THREAT`  *{active_item['label']}*\n_Dropped — won't be part of this test._"}})
        else:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":large_blue_diamond: `THREAT`  *{active_item['label']}*\n_{active_item['why']}_"}})

            # Incident tabs, reusing the same real taxonomy the later
            # Threat map step already has (same threat IDs) -- shown
            # immediately, no extra click, causes listed straight under
            # the selected incident (the deepest level, so no tab needed).
            raw_key = active_item["key"]
            incidents = []
            if not active_item["custom"]:
                from .threat_map_v2_data import _find_threat

                taxonomy_threat = _find_threat(active_module, raw_key)
                incidents = taxonomy_threat["incidents"] if taxonomy_threat else []

            if incidents:
                active_incident = state.get("active_incident")
                if not any(inc["id"] == active_incident for inc in incidents):
                    active_incident = incidents[0]["id"]

                inc_tab_elements = [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": inc["name"], "emoji": True},
                        "action_id": f"v2_threat_incident_tab__{inc['id']}",
                        "value": inc["id"],
                        **({"style": "primary"} if inc["id"] == active_incident else {}),
                    }
                    for inc in incidents
                ]
                blocks.append({"type": "actions", "block_id": f"threatinc|{active_incident}", "elements": inc_tab_elements})

                selected_incident = next((inc for inc in incidents if inc["id"] == active_incident), None)
                if selected_incident:
                    blocks.append(
                        {"type": "section", "text": {"type": "mrkdwn", "text": f":large_purple_circle: `INCIDENT`  *{selected_incident['name']}*"}}
                    )
                    for cause in selected_incident["causes"]:
                        blocks.append(
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": f":large_green_circle: `CAUSE`  {cause['name']}"},
                                "accessory": {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "See scenarios →", "emoji": True},
                                    "action_id": f"v2_threat_pick_cause__{cause['id']}",
                                    "value": f"{active_module}:{raw_key}:{selected_incident['id']}:{cause['id']}",
                                },
                            }
                        )
            elif not active_item["custom"]:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No incidents mapped for this threat yet._"}]})

    blocks.append({"type": "divider"})

    if form is not None:
        blocks.extend(_add_form_blocks(form, custom))

    blocks.append({"type": "divider"})
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Pick a cause above and click \"See scenarios\" to continue._"}]}
    )

    return {"blocks": blocks}
