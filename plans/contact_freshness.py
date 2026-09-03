"""
B5: contact freshness check. "Confirms that every named responder still
exists in the directory and still holds the stated role."

"Still holds the stated role" would need us to know what role the plan
claims for each contact (real structured extraction, not built yet -- see
structured_extraction.py's limitations). What's here is the first half:
confirming each extracted email still corresponds to an active member of
the Slack workspace, using users.lookupByEmail.
"""

import logging

import requests

logger = logging.getLogger(__name__)

SLACK_LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"

STATUS_ACTIVE = "active"
STATUS_DEACTIVATED = "deactivated"
STATUS_NOT_FOUND = "not_found"
STATUS_UNKNOWN = "unknown"  # lookup itself failed (network/API error)


def check_contacts(emails: list[str], bot_token: str) -> list[dict]:
    """
    Returns [{"email": ..., "status": ..., "display_name": ...}, ...] for
    each email, checked against the Slack workspace directory -- always
    the workspace that owns `bot_token`, never a different client's.
    """
    if not bot_token:
        return [
            {"email": e, "status": STATUS_UNKNOWN, "display_name": None} for e in emails
        ]

    return [_check_one(email, bot_token) for email in emails]


def _check_one(email: str, bot_token: str) -> dict:
    try:
        resp = requests.get(
            SLACK_LOOKUP_URL,
            headers={"Authorization": f"Bearer {bot_token}"},
            params={"email": email},
            timeout=10,
        ).json()
    except requests.RequestException:
        logger.exception("Slack users.lookupByEmail failed for %s", email)
        return {"email": email, "status": STATUS_UNKNOWN, "display_name": None}

    if not resp.get("ok"):
        if resp.get("error") == "users_not_found":
            return {"email": email, "status": STATUS_NOT_FOUND, "display_name": None}
        logger.warning("users.lookupByEmail error for %s: %s", email, resp.get("error"))
        return {"email": email, "status": STATUS_UNKNOWN, "display_name": None}

    user = resp.get("user", {})
    is_deactivated = user.get("deleted", False)
    return {
        "email": email,
        "status": STATUS_DEACTIVATED if is_deactivated else STATUS_ACTIVE,
        "display_name": user.get("real_name") or user.get("name"),
    }


def gaps_from_contact_checks(contact_checks: list[dict]) -> list[dict]:
    """Extra plan gaps (see gap_review.py) for contacts that failed freshness checks."""
    gaps = []
    for check in contact_checks:
        if check["status"] == STATUS_NOT_FOUND:
            gaps.append(
                {
                    "code": "contact_not_in_directory",
                    "message": f"{check['email']} is named in the plan but isn't in this Slack workspace.",
                }
            )
        elif check["status"] == STATUS_DEACTIVATED:
            gaps.append(
                {
                    "code": "contact_deactivated",
                    "message": f"{check['email']} ({check['display_name']}) is a deactivated Slack account.",
                }
            )
    return gaps
