"""
TestMyPlan Threats Center -- sir's call: a separate, standalone entry
point (own message, reached via /testmyplan threats, not a step in the
Welcome -> ... -> Trigger nav bar) that shows the org's threats only up
to Threat level -- Module (Cybersecurity / Privacy) -> Criticality
(Critical / High / Med) -> Threat -- with no Incident/Cause/Phase/
Scenario drill-down here. One button, "Launch Test", hands off into the
existing full Threat Profile card (threats_v2_data.build_org_threats_card)
pre-seeded at the same Module/Criticality/Threat, where the admin finishes
picking Incident -> Cause -> Phase -> Scenario and actually triggers.

Reuses the exact same THREATS/MODULES/CRIT_* data and block_id scheme as
threats_v2_data.py so both cards stay in sync with one source of truth.
"""

from .slack_client import SlackApiError, _call
from .threats_v2_data import CRIT_EMOJI, CRIT_OPTIONS, MODULES, THREATS

MODULE_ICON = {"Cybersecurity": ":shield:", "Privacy": ":lock:"}

CHANNEL_NAME = "testmyplan-threats-center"


def get_or_create_channel(slack_team_id: str, inviter_slack_user_id: str, bot_token: str) -> str:
    """
    Real dedicated channel, created once per workspace -- reused on every
    later /testmyplan threats run instead of spawning a new one each time.
    Returns the channel id, or "" if it couldn't be created/found.
    """
    from . import persistence_v2

    setup = persistence_v2._get_or_create(slack_team_id)
    if setup.threats_center_channel_id:
        return setup.threats_center_channel_id

    try:
        created = _call("conversations.create", bot_token, name=CHANNEL_NAME, is_private=False)
        channel_id = created["channel"]["id"]
    except SlackApiError:
        # Most likely name_taken (channel already exists from a previous
        # run that failed to save) -- look it up instead of failing.
        try:
            listing = _call("conversations.list", bot_token, exclude_archived=True, limit=200)
            match = next((c for c in listing.get("channels", []) if c.get("name") == CHANNEL_NAME), None)
            channel_id = match["id"] if match else ""
        except SlackApiError:
            channel_id = ""

    if not channel_id:
        return ""

    if inviter_slack_user_id:
        try:
            _call("conversations.invite", bot_token, channel=channel_id, users=inviter_slack_user_id)
        except SlackApiError:
            pass  # not fatal -- channel still usable, they can be added manually

    setup.threats_center_channel_id = channel_id
    setup.save()
    return channel_id


def read_current_state(message_blocks: list) -> dict:
    message_blocks = message_blocks or []
    active_module = MODULES[0]
    active_crit = None
    active_threat = None
    fixed = {}

    for block in message_blocks:
        block_id = block.get("block_id", "")
        if block_id.startswith("tcmodule|"):
            active_module = block_id.removeprefix("tcmodule|")
        elif block_id.startswith("tccrit|"):
            active_crit = block_id.removeprefix("tccrit|")
        elif block_id.startswith("tcthreat|"):
            active_threat = block_id.removeprefix("tcthreat|")

    return {"active_module": active_module, "active_crit": active_crit, "active_threat": active_threat, "fixed": fixed}


def build_threats_center_card(state: dict, team_id: str = "") -> dict:
    threats = THREATS
    if team_id:
        from plans.threat_ranking import rank_threats

        threats = rank_threats(team_id, THREATS)

    fixed_state = state.get("fixed", {})
    active_module = state.get("active_module") or MODULES[0]

    counts = {"Critical": 0, "High": 0, "Med": 0}
    for t in threats:
        crit = fixed_state.get(t["key"], t["default_crit"])
        if crit in counts:
            counts[crit] += 1

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: TestMyPlan Threats Center", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f":red_circle: *{counts['Critical']}* Critical   |   "
                        f":large_orange_circle: *{counts['High']}* High   |   "
                        f":large_yellow_circle: *{counts['Med']}* Med"
                    ),
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ">A fast view of everything your org is exposed to. Pick a module, a criticality, then a threat -- and launch straight into a test.",
            },
        },
        {"type": "divider"},
    ]

    # Module tabs
    tab_elements = []
    for module in MODULES:
        mod_threats = [t for t in threats if t["module"] == module]
        tab_elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{MODULE_ICON.get(module, '')} {module} ({len(mod_threats)})", "emoji": True},
                "action_id": f"v2_tc_module_tab__{module}",
                "value": module,
                **({"style": "primary"} if module == active_module else {}),
            }
        )
    blocks.append({"type": "actions", "block_id": f"tcmodule|{active_module}", "elements": tab_elements})
    blocks.append({"type": "divider"})

    mod_items = [
        {"key": t["key"], "label": t["label"], "crit": fixed_state.get(t["key"], t["default_crit"]), "why": t["why"], "icon": t["icon"]}
        for t in threats if t["module"] == active_module
    ]

    # Criticality tabs -- only ones that actually have a threat
    present_crits = [c for c in CRIT_OPTIONS if c != "Dropped" and any(i["crit"] == c for i in mod_items)]
    active_crit = state.get("active_crit")
    if active_crit not in present_crits:
        active_crit = None

    if present_crits:
        crit_tab_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{CRIT_EMOJI[c]} {c} ({sum(1 for i in mod_items if i['crit'] == c)})", "emoji": True},
                "action_id": f"v2_tc_crit_tab__{c}",
                "value": c,
                **({"style": "primary"} if c == active_crit else {}),
            }
            for c in present_crits
        ]
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "`CRITICALITY`"}]})
        blocks.append({"type": "actions", "block_id": f"tccrit|{active_crit or ''}", "elements": crit_tab_elements})

    items_in_crit = [i for i in mod_items if i["crit"] == active_crit] if active_crit else []

    active_threat = state.get("active_threat")
    if not any(i["key"] == active_threat for i in items_in_crit):
        active_threat = None

    if items_in_crit:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "`THREAT`"}]})
        threat_tab_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{i['icon']} {i['label']}", "emoji": True},
                "action_id": f"v2_tc_threat_tab__{i['key']}",
                "value": i["key"],
                **({"style": "primary"} if i["key"] == active_threat else {}),
            }
            for i in items_in_crit
        ]
        blocks.append({"type": "actions", "block_id": f"tcthreat|{active_threat or ''}", "elements": threat_tab_elements})

    active_item = next((i for i in items_in_crit if i["key"] == active_threat), None)
    if active_item:
        emoji = CRIT_EMOJI[active_item["crit"]]
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{active_item['icon']} *{active_item['label']}*  {emoji} _{active_item['crit']}_\n_{active_item['why']}_"},
            }
        )
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":rocket: Launch Test", "emoji": True},
                        "action_id": "v2_tc_launch",
                        "value": f"{active_module}|{active_crit}|{active_threat}",
                        "style": "danger",
                    }
                ],
            }
        )

    return {"blocks": blocks}
