"""
Nav bar ("wrapper") for the new design preview (cards/blocks_v2/) --
same mechanism as cards/nav.py (a row of buttons, active step
highlighted), just a different, separate set of steps matching the new
design's flow. Kept fully separate from nav.py so nothing here can
ever affect the real, live command-center cards.
"""

NAV_STEPS_V2 = [
    ("Welcome", "welcome"),
    ("Admins", "admins"),
    ("Configure Teams", "teams"),
    ("Threat Profile", "org_threats"),
    ("TestMyPlan", "test_plan"),
]


def build_nav_block_v2(active_key: str) -> dict:
    return {
        "type": "actions",
        "block_id": "wizard_nav_v2",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "action_id": f"v2_nav_jump__{key}",
                "value": key,
                **({"style": "primary"} if key == active_key else {}),
            }
            for label, key in NAV_STEPS_V2
        ],
    }


def with_nav_bar_v2(card: dict, active_key: str) -> dict:
    card = dict(card)
    card["blocks"] = [build_nav_block_v2(active_key)] + list(card.get("blocks", []))
    return card
