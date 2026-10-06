"""
"Organization Details" step (nav tab 2, between Welcome and Admins) --
matches the latest design (new slack design (5)/index.html's SetupCard).
Org name + website URL need free text, so those go through a real Slack
modal; industry is a dropdown, regions/regulations are toggleable pills
-- all handled inline on the card itself, same pattern as every other
v2 card in this app.
"""

import json

import requests

from .models_v2 import OrgProfile

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_org_setup_modal"

INDUSTRY_OPTIONS = [
    "Healthcare", "Financial Services", "Retail", "Manufacturing", "Technology",
    "Legal", "Education", "Government", "Energy", "Other",
]
REGION_OPTIONS = ["North America", "UK", "EU", "APAC", "Middle East", "Other"]
REGULATION_OPTIONS = ["GDPR", "HIPAA", "NIS2", "DSPT", "SOC 2", "PCI DSS", "Not sure yet"]


def load_profile(team_id: str) -> dict:
    profile = OrgProfile.objects(team_id=team_id).first()
    if profile is None:
        return {"org_name": "", "industry": "", "website_url": "", "regions": [], "regulations": []}
    return {
        "org_name": profile.org_name or "",
        "industry": profile.industry or "",
        "website_url": profile.website_url or "",
        "regions": list(profile.regions),
        "regulations": list(profile.regulations),
    }


def save_profile(team_id: str, **fields) -> None:
    profile = OrgProfile.objects(team_id=team_id).first() or OrgProfile(team_id=team_id)
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.save()


def _select_option(value: str) -> dict:
    return {"text": {"type": "plain_text", "text": value}, "value": value}


def _is_complete(profile: dict) -> bool:
    return bool(profile["org_name"].strip() and profile["website_url"].strip() and profile["industry"])


def build_setup_card(profile: dict) -> dict:
    complete = _is_complete(profile)
    # Sir's call: this is captured on the website signup form now, before
    # Slack install -- this card just displays what was already entered
    # and lets them fix mistakes, it doesn't collect it for the first time
    # anymore (except as a fallback if the website form was skipped).
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":dart: Step · Organization Details", "emoji": True}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": (":large_green_circle: *Ready*" if complete else ":white_circle: *Missing details — click Edit*")}],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Captured when you signed up on the website. If anything's wrong, fix it here.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "block_id": "orgsetup_summary",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Organization name*\n{profile['org_name'] or '_Not set_'}\n\n"
                    f"*Website URL*\n{profile['website_url'] or '_Not set_'}\n\n"
                    f"*Industry*\n{profile['industry'] or '_Not set_'}\n\n"
                    f"*Where you operate*\n{', '.join(profile['regions']) or '_Not set_'}\n\n"
                    f"*Regulations*\n{', '.join(profile['regulations']) or '_Not set_'}"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit details", "emoji": True},
                "action_id": "v2_orgsetup_edit",
                "value": "edit",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "→ Continue", "emoji": True},
                    "action_id": "v2_orgsetup_continue",
                    "value": "continue",
                    **({"style": "primary"} if complete else {}),
                }
            ],
        },
    ]
    if not complete:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Fill in organization name, website URL and industry to continue._"}]}
        )
    return {"blocks": blocks}


def build_modal_view(profile: dict, channel_id: str, message_ts: str) -> dict:
    industry = profile.get("industry", "")
    industry_element = {
        "type": "static_select",
        "action_id": "value",
        "options": [_select_option(o) for o in INDUSTRY_OPTIONS],
    }
    if industry and industry in INDUSTRY_OPTIONS:
        industry_element["initial_option"] = _select_option(industry)
    else:
        industry_element["placeholder"] = {"type": "plain_text", "text": "Select…"}

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Organization details"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "org_name",
                "label": {"type": "plain_text", "text": "Organization name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "initial_value": profile.get("org_name", ""),
                    "placeholder": {"type": "plain_text", "text": "e.g. Acme Health Systems"},
                },
            },
            {
                "type": "input",
                "block_id": "industry",
                "label": {"type": "plain_text", "text": "Industry"},
                "element": industry_element,
            },
            {
                "type": "input",
                "block_id": "website_url",
                "label": {"type": "plain_text", "text": "Website URL"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "initial_value": profile.get("website_url", ""),
                    "placeholder": {"type": "plain_text", "text": "https://yourcompany.com"},
                },
            },
            {
                "type": "input",
                "block_id": "regions",
                "label": {"type": "plain_text", "text": "Where do you operate?"},
                "optional": True,
                "element": {
                    "type": "multi_static_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Select regions…"},
                    "options": [_select_option(r) for r in REGION_OPTIONS],
                    **(
                        {"initial_options": [_select_option(r) for r in profile.get("regions", []) if r in REGION_OPTIONS]}
                        if profile.get("regions")
                        else {}
                    ),
                },
            },
            {
                "type": "input",
                "block_id": "regulations",
                "label": {"type": "plain_text", "text": "Regulations that apply (if known)"},
                "optional": True,
                "element": {
                    "type": "multi_static_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Select regulations…"},
                    "options": [_select_option(r) for r in REGULATION_OPTIONS],
                    **(
                        {"initial_options": [_select_option(r) for r in profile.get("regulations", []) if r in REGULATION_OPTIONS]}
                        if profile.get("regulations")
                        else {}
                    ),
                },
            },
        ],
    }


def open_modal(trigger_id: str, team_id: str, channel_id: str, message_ts: str, bot_token: str) -> None:
    profile = load_profile(team_id)
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(profile, channel_id, message_ts)},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    team_id = payload.get("team", {}).get("id", "")

    values = view.get("state", {}).get("values", {})
    org_name = (values.get("org_name", {}).get("value", {}).get("value") or "").strip()
    website_url = (values.get("website_url", {}).get("value", {}).get("value") or "").strip()
    industry = values.get("industry", {}).get("value", {}).get("selected_option") or {}
    industry_value = industry.get("value", "")
    regions = [o["value"] for o in (values.get("regions", {}).get("value", {}).get("selected_options") or [])]
    regulations = [o["value"] for o in (values.get("regulations", {}).get("value", {}).get("selected_options") or [])]

    from accounts.views import _is_valid_website_url

    invalid_url = bool(website_url) and not _is_valid_website_url(website_url)
    if invalid_url:
        # Modal submissions in this app are handled in the background (see
        # cards/views.py's _run_in_background), so there's no way to show
        # Slack's real-time inline field error here -- keep the previous
        # good value instead of saving garbage, and tell them by DM.
        website_url = load_profile(team_id).get("website_url", "")

    save_profile(
        team_id, org_name=org_name, website_url=website_url, industry=industry_value,
        regions=regions, regulations=regulations,
    )

    if invalid_url:
        user_id = payload.get("user", {}).get("id", "")
        if user_id and bot_token:
            from .slack_client import _call

            try:
                opened = _call("conversations.open", bot_token, users=user_id)
                _call(
                    "chat.postMessage",
                    bot_token,
                    channel=opened["channel"]["id"],
                    text=":warning: That website URL didn't look valid -- kept your previous value. Everything else you changed was saved.",
                )
            except Exception:
                pass

    if not (channel_id and message_ts and bot_token):
        return

    from .nav_v2 import with_nav_bar_v2

    profile = load_profile(team_id)
    card = with_nav_bar_v2(build_setup_card(profile), "org_setup")
    requests.post(
        f"{SLACK_API_BASE}/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    )
