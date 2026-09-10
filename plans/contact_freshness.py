"""
B5: contact freshness check. "Confirms that every named responder still
exists in the directory and still holds the stated role."

"Still holds the stated role" would need us to know what role the plan
claims for each contact (real structured extraction, not built yet -- see
structured_extraction.py's limitations). What's here confirms each
extracted contact still corresponds to an active member of the Slack
workspace -- by email when the plan has one (users.lookupByEmail), and
by name otherwise (matching against the workspace directory, since a
lot of real BIAs list a contact's name and phone but not their email --
confirmed with the actual SecureItLab sample, whose 3 contacts were all
phone-only).
"""

import logging

import requests

logger = logging.getLogger(__name__)

SLACK_LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"
SLACK_USERS_LIST_URL = "https://slack.com/api/users.list"

STATUS_ACTIVE = "active"
STATUS_DEACTIVATED = "deactivated"
STATUS_NOT_FOUND = "not_found"
STATUS_UNVERIFIABLE = "unverifiable"  # no email or name to check against
STATUS_UNKNOWN = "unknown"  # lookup itself failed (network/API error)


def check_contacts(contacts, bot_token: str) -> list[dict]:
    """
    `contacts` is either a plain list of email strings (the old regex
    extraction's shape) or a list of {"name", "email", "phone", ...}
    dicts (AI extraction's shape, plans/ai_extraction.py). Returns
    [{"email"/"name": ..., "status": ..., "display_name": ...}, ...].
    """
    normalized = [
        {"email": c, "name": None} if isinstance(c, str) else {"email": c.get("email"), "name": c.get("name")}
        for c in contacts
    ]

    if not bot_token:
        return [
            {**c, "status": STATUS_UNKNOWN, "display_name": None} for c in normalized
        ]

    # Only fetch the full member directory if we'll actually need it --
    # most workspaces have every contact with a real email, and this is
    # one extra Slack API call per upload otherwise.
    needs_directory = any(not c["email"] and c["name"] for c in normalized)
    directory = _fetch_user_directory(bot_token) if needs_directory else []

    return [_check_one(c, bot_token, directory) for c in normalized]


def _check_one(contact: dict, bot_token: str, directory: list[dict]) -> dict:
    email, name = contact["email"], contact["name"]

    if email:
        return {**contact, **_lookup_by_email(email, bot_token)}
    if name:
        return {**contact, **_match_by_name(name, directory)}
    return {**contact, "status": STATUS_UNVERIFIABLE, "display_name": None}


def _lookup_by_email(email: str, bot_token: str) -> dict:
    try:
        resp = requests.get(
            SLACK_LOOKUP_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
            params={"email": email},
            timeout=10,
        ).json()
    except requests.RequestException:
        logger.exception("Slack users.lookupByEmail failed for %s", email)
        return {"status": STATUS_UNKNOWN, "display_name": None}

    if not resp.get("ok"):
        if resp.get("error") == "users_not_found":
            return {"status": STATUS_NOT_FOUND, "display_name": None}
        logger.warning("users.lookupByEmail error for %s: %s", email, resp.get("error"))
        return {"status": STATUS_UNKNOWN, "display_name": None}

    user = resp.get("user", {})
    return {
        "status": STATUS_DEACTIVATED if user.get("deleted", False) else STATUS_ACTIVE,
        "display_name": user.get("real_name") or user.get("name"),
    }


def _fetch_user_directory(bot_token: str) -> list[dict]:
    try:
        resp = requests.get(
            SLACK_USERS_LIST_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=10,
        ).json()
    except requests.RequestException:
        logger.exception("Slack users.list failed")
        return []

    if not resp.get("ok"):
        logger.warning("users.list error: %s", resp.get("error"))
        return []
    return resp.get("members", [])


def _match_by_name(name: str, directory: list[dict]) -> dict:
    """
    A plan names people, not Slack user IDs -- this is a best-effort,
    case-insensitive match against real_name/display_name. Titles like
    "Head of Managed Services" (a role, not a person's actual name --
    common in real BIAs when the position is named instead of the
    incumbent) won't match anyone, which correctly comes back as
    "not_found" rather than a false positive.
    """
    target = name.strip().lower()
    for user in directory:
        profile = user.get("profile", {})
        candidates = [profile.get("real_name", ""), profile.get("display_name", ""), user.get("name", "")]
        if any(target == c.strip().lower() for c in candidates if c):
            return {
                "status": STATUS_DEACTIVATED if user.get("deleted", False) else STATUS_ACTIVE,
                "display_name": profile.get("real_name") or user.get("name"),
            }
    return {"status": STATUS_NOT_FOUND, "display_name": None}


def gaps_from_contact_checks(contact_checks: list[dict]) -> list[dict]:
    """Extra plan gaps (see gap_review.py) for contacts that failed freshness checks."""
    gaps = []
    for check in contact_checks:
        label = check.get("email") or check.get("name") or "A named contact"
        if check["status"] == STATUS_NOT_FOUND:
            gaps.append(
                {
                    "code": "contact_not_in_directory",
                    "message": f"{label} is named in the plan but isn't in this Slack workspace.",
                }
            )
        elif check["status"] == STATUS_DEACTIVATED:
            gaps.append(
                {
                    "code": "contact_deactivated",
                    "message": f"{label} ({check['display_name']}) is a deactivated Slack account.",
                }
            )
        elif check["status"] == STATUS_UNVERIFIABLE:
            gaps.append(
                {
                    "code": "contact_unverifiable",
                    "message": f"{label} has no email or name to verify against the Slack directory.",
                }
            )
    return gaps
