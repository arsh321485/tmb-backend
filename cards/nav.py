"""
Tab-like navigation for the setup wizard cards. Real Slack buttons can't
be styled as a pill-shaped tab bar (only 3 fixed styles exist: default,
primary, danger) -- this gives the same *function* as tabs (jump to any
step, not just move forward one at a time), using the active step
highlighted in the "primary" (green) button style instead.

Covers every wizard card, not just the first few -- without this, going
past the early steps left no way back once a card without a nav bar
replaced the message (confirmed live: user got stuck on the
Preparedness report card with no way back to Welcome).
"""

# (label, key, card filename) -- order is display order in the nav bar.
NAV_STEPS = [
    ("Welcome", "welcome", "01-welcome.json"),
    ("Add admin", "admin", "02-admin-team.json"),
    ("Teams", "teams", "03-response-teams.json"),
    ("Threat map", "threat", "05-threat-map.json"),
    ("BIA / Scenario", "bia", "06-bia-needed.json"),
    ("Scenario", "scenario", "08-scenario.json"),
    ("Test plan", "plan", "09-test-plan.json"),
    ("Trigger", "trigger", "10-trigger.json"),
    ("Live", "live", "11-test-live.json"),
    ("Report", "report", "23-preparedness-report.json"),
]

# Card files that are "the same step" as one of the ones above for nav
# purposes, even though they're a different JSON file (e.g. bia-ready is
# still the BIA/Scenario step, just after the plan's uploaded).
_FILE_ALIASES = {
    "07-bia-ready.json": "bia",
}

_KEY_TO_FILE = {key: filename for _, key, filename in NAV_STEPS}
_FILE_TO_KEY = {filename: key for _, key, filename in NAV_STEPS}
_FILE_TO_KEY.update(_FILE_ALIASES)


def card_file_for_nav_key(key: str) -> str | None:
    return _KEY_TO_FILE.get(key)


def nav_key_for_card_file(filename: str) -> str | None:
    return _FILE_TO_KEY.get(filename)


def build_nav_block(active_key: str) -> dict:
    return {
        "type": "actions",
        "block_id": "wizard_nav",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                # Slack requires action_id to be unique per message -- each
                # nav button gets its own (nav_jump__welcome, etc.); value
                # still carries which step to jump to.
                "action_id": f"nav_jump__{key}",
                "value": key,
                **({"style": "primary"} if key == active_key else {}),
            }
            for label, key, _ in NAV_STEPS
        ],
    }


def with_nav_bar(card: dict, active_key: str) -> dict:
    """Returns a copy of `card` with the nav row inserted as its first block."""
    card = dict(card)
    card["blocks"] = [build_nav_block(active_key)] + list(card.get("blocks", []))
    return card
