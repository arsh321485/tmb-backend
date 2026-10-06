"""
Real workspace members for the new-design preview's people-pickers
(Admins, Teams) -- replaces the old mock list (Sofia/Tomas/James/...)
with actual Slack accounts via users.list, so assigning someone for
real means picking a real, DM-able person.
"""

import requests

SLACK_API_BASE = "https://slack.com/api"


def get_workspace_people(bot_token: str) -> list[dict]:
    """
    Returns [{"i": slack_user_id, "n": display_name}, ...] -- real
    members only: excludes bots, deactivated accounts, and Slackbot
    itself (never a real assignable person).
    """
    if not bot_token:
        return []

    people = []
    cursor = ""
    for _ in range(10):  # hard cap -- a workspace this large is unlikely in testing, avoids an infinite loop on a weird cursor
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(
            f"{SLACK_API_BASE}/users.list",
            headers={"Authorization": f"Bearer {bot_token}"},
            params=params,
            timeout=10,
        ).json()
        if not resp.get("ok"):
            break

        for m in resp.get("members", []):
            if m.get("is_bot") or m.get("deleted") or m.get("id") == "USLACKBOT":
                continue
            profile = m.get("profile", {})
            name = profile.get("real_name") or m.get("name") or m["id"]
            people.append({"i": m["id"], "n": name})

        cursor = resp.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break

    return people
