"""
Nav bar for the participant-side test flow (cards/user_flow_test.py,
#ir-war-room) -- same button-row mechanism as cards/nav_v2.py, just a
separate set of steps for the user_screen design. Clicking a step here
just re-shows that card (test only, no real state).
"""

NAV_STEPS_USER_TEST = [
    ("Welcome", "welcome"),
    ("Join exercise", "join"),
]


def build_nav_block_user_test(active_key: str) -> dict:
    return {
        "type": "actions",
        "block_id": "user_test_nav",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "action_id": f"v2_test_nav_jump__{key}",
                "value": key,
                **({"style": "primary"} if key == active_key else {}),
            }
            for label, key in NAV_STEPS_USER_TEST
        ],
    }


def with_nav_bar_user_test(blocks: list, active_key: str) -> list:
    return [build_nav_block_user_test(active_key)] + list(blocks)
