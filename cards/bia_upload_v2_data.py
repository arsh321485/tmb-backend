"""
New wizard step between Admins and Threat Profile: "Upload BIA/BCP &
Analysis" -- combined into one screen (sir's call: two tabs for one
real action -- DM a file -- was confusing, and the real fix for "it
takes forever to show up" was a live push, not a second tab; keeping
them separate would still have needed that same push).

Brand new screen -- this only READS the real Plan the org already
uploaded through the existing, proven DM-drop pipeline (plans/intake.py's
handle_dm_message_event, unmodified). No new upload mechanics here, just
a status + analysis card pointing at that real pipeline and showing what
it found. The live auto-refresh after a DM upload finishes lives in
home_tab/views.py, wrapping the call instead of editing intake.py.
"""

import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

# Slack caps a message at 50 blocks total; each service takes 1 block,
# with ~8 more used by the header/intro/impacts/buttons around them --
# this is a real safety ceiling for an org with an unusually long
# service list, not an arbitrary display choice (so it should never
# trigger for a normal BIA/BCP).
MAX_SERVICES_SHOWN = 40

HEADER = {"type": "header", "text": {"type": "plain_text", "text": ":open_file_folder: Step · Upload & Analyze your BIA / BCP", "emoji": True}}


def _latest_plan(team_id: str):
    from plans.models import Plan

    return Plan.objects(slack_team_id=team_id, is_latest=True).order_by("-created_at").first()


def _dm_redirect_url(team_id: str, user_id: str = "", bot_token: str = "") -> str:
    """Deep link for "Want to change the file?"/"Open DM" buttons.
    Sir's call: app_redirect with app= opens this app's Home tab first
    (since this app has one) -- the admin wants it to land straight on
    the Messages/DM tab instead.

    Two earlier attempts both confirmed LIVE (sir's own clicks) to
    still land on Home: app_redirect?channel=... (not actually a
    documented app_redirect param) and the bare conversation link
    https://app.slack.com/client/TEAM/CHANNEL (an app that has a Home
    tab apparently shows its DM as one tabbed surface, and a bare
    channel link reopens to whichever tab is sticky -- Home). The one
    real mechanism that forces the Messages tab specifically is a
    MESSAGE permalink -- a link to one real message inside that DM,
    not just the channel -- since jumping to a specific message only
    makes sense inside Messages. Built from the most recent real
    message already in that DM (this app always DMs the admin at least
    once already, e.g. the intro DM) via chat.getPermalink. Falls back
    to the old app= (Home tab) link if there's no user_id/bot_token, or
    if that DM genuinely has no message yet to permalink to."""
    if user_id and bot_token:
        try:
            from .slack_client import SlackApiError, _call

            resp = _call("conversations.open", bot_token, users=user_id)
            channel_id = resp.get("channel", {}).get("id", "")
            if channel_id:
                history = _call("conversations.history", bot_token, channel=channel_id, limit=1)
                messages = history.get("messages", [])
                if messages:
                    # chat.getPermalink is one of the few Slack methods
                    # that rejects a JSON body (confirmed live:
                    # invalid_arguments via _call's json= POST) -- needs
                    # form-encoded params instead.
                    import requests

                    perma_resp = requests.get(
                        "https://slack.com/api/chat.getPermalink",
                        headers={"Authorization": f"Bearer {bot_token}"},
                        params={"channel": channel_id, "message_ts": messages[0]["ts"]},
                        timeout=10,
                    ).json()
                    link = perma_resp.get("permalink", "") if perma_resp.get("ok") else ""
                    if link:
                        return link
        except SlackApiError:
            logger.exception("Couldn't resolve a DM permalink for %s -- falling back to app Home link", user_id)
    return f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}"


def build_bia_question_card() -> dict:
    """First thing shown on this step, before any upload instructions
    (flowchart's "BCP/BIA available?" decision) -- Yes leads to the
    upload instructions below, No points at the GRC Department instead.
    Rendered as a real image (sir's "Upload & analyze your BIA / BCP"
    design) -- same template-code approach as the other cards. Entirely
    static content, so this is one cached image reused for everyone.
    The Yes/Not yet buttons stay real Slack buttons underneath it."""
    from django.conf import settings

    from .upload_intro_card_image import get_upload_intro_card_image_url

    image_url = get_upload_intro_card_image_url(settings.BACKEND_URL)
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Upload & analyze your BIA / BCP"},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": ":white_check_mark: Yes, I have it", "emoji": True}, "action_id": "v2_bia_have_doc_yes", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": ":no_entry_sign: Not yet", "emoji": True}, "action_id": "v2_bia_have_doc_no"},
                ],
            },
        ]
    }


def build_grc_department_card() -> dict:
    """The "No" answer -- flowchart routes this to the GRC Department to
    prepare the document first, rather than to the upload instructions.
    Also offers a second, faster option (sir's call): generate a draft
    ourselves instead of GRC's ~4 week turnaround, for a client who
    doesn't want to wait or pay extra for that. Rendered as a real
    image (sir's design) -- same template-code approach as the other
    cards. Entirely static content, so this is one cached image reused
    for everyone. The two action buttons stay real Slack buttons
    underneath it."""
    from django.conf import settings

    from .grc_department_card_image import get_grc_department_card_image_url

    image_url = get_grc_department_card_image_url(settings.BACKEND_URL)
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Choose your path"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":white_check_mark: I have it now", "emoji": True},
                        "action_id": "v2_bia_have_doc_yes",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":sparkles: Generate a draft for us instead", "emoji": True},
                        "action_id": "v2_bia_generate_draft",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":bulb: Either way, nothing is final until you've reviewed and approved it."}],
            },
        ]
    }


def build_draft_requested_card(team_id: str) -> dict:
    """Shown right after the client asks for a generated draft -- confirms
    we have real org_name/website_url to work from (from signup, not
    asked again here) and that the request is recorded. Same
    template-image approach as the other converted screens -- the
    image carries org_name/website_url (keyed into its cache hash so
    it regenerates per org), and the "Check again" button stays a
    real Slack button underneath it. No separate HEADER block here --
    the image's own logo+badge already is the header."""
    from django.conf import settings

    from .draft_requested_card_image import get_draft_requested_card_image_url
    from .models_v2 import OrgProfile

    profile = OrgProfile.objects(team_id=team_id).first() if team_id else None
    org_name = (profile.org_name if profile else "") or "your organization"
    website_url = (profile.website_url if profile else "") or "not on file"

    image_url = get_draft_requested_card_image_url(settings.BACKEND_URL, org_name, website_url)
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Draft request received"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    }
                ],
            },
        ]
    }


def build_draft_failed_card(team_id: str, user_id: str = "", bot_token: str = "") -> dict:
    """Shown when plans/draft_generation.py's research genuinely failed
    -- replaces the old silent-forever "pending" state (sir's call:
    don't leave the user guessing why nothing ever shows up)."""
    from .models_v2 import DraftBiaRequest

    req = DraftBiaRequest.objects(team_id=team_id).first() if team_id else None
    message = (req.error_message if req else "") or "Something went wrong and we're not sure why."

    return {
        "blocks": [
            HEADER,
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: *We couldn't generate a draft.*\n{message}"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Try again", "emoji": True},
                        "action_id": "v2_bia_generate_draft",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Want to change the file? Click here", "emoji": True},
                        "action_id": "v2_bia_refresh",
                        "url": _dm_redirect_url(team_id, user_id, bot_token),
                    },
                ],
            },
        ]
    }


def _rto_tier(rto_text: str) -> str:
    """Buckets an RTO into "urgent" (<=1 day), "warn" (<=5 days), or
    "calm" (longer, or unreadable) -- purely a display tier for the
    services image's RTO pill color, same urgency scale as the sort
    order below."""
    from plans.threat_ranking import _rto_to_hours

    hours = _rto_to_hours(rto_text or "")
    if hours is None:
        return "calm"
    if hours <= 24:
        return "urgent"
    if hours <= 120:
        return "warn"
    return "calm"


def _services_groups(plan) -> tuple:
    """Returns (rows, overflow_count, found_text) for the services
    template image -- rows is a flat, most-urgent-first list of
    (name, rto, tier) tuples (sir's design drops the old Services/
    Technology/Applications sub-headers in favor of one plain numbered
    list), handed to the image renderer instead of built as Slack
    blocks."""
    from plans.threat_ranking import _rto_to_hours

    services = (plan.resilience_map or {}).get("services") or []

    if not services:
        return [], 0, "The AI didn't find any named services/processes with recovery objectives in this document."

    # Sir's call: shortest RTO (most urgent) first, not whatever order
    # the document happened to list them in. A service with no readable
    # RTO sorts last, not first -- it shouldn't look more urgent than
    # one that actually has a real number just because it's unreadable.
    def _sort_key(svc: dict) -> float:
        hours = _rto_to_hours(svc.get("rto") or "")
        return hours if hours is not None else float("inf")

    services = sorted(services, key=_sort_key)
    found_text = f"Found {len(services)} services with an RTO"

    shown = services[:MAX_SERVICES_SHOWN]
    overflow_count = len(services) - len(shown)
    rows = [
        ((s.get("name") or "Unnamed item"), (s.get("rto") or "not stated"), _rto_tier(s.get("rto") or ""))
        for s in shown
    ]
    return rows, overflow_count, found_text


def send_upload_prompt_dm(team_id: str, user_id: str, bot_token: str) -> None:
    """
    Proactively drops "Upload your BIA/BCP here" straight into the
    person's own DM with this app (sir's call) -- the "Open DM with
    TestMyPlan" button used to just open an empty conversation with no
    hint of what to do once they got there.

    Called explicitly from the "Yes, I have it" / "I have it now"
    button clicks ONLY (cards/interactivity_v2.py) -- NOT from inside
    build_bia_upload_card itself, which redraws this same screen for
    several other reasons too (Check again, Make changes, a DM upload
    finishing, ...) that shouldn't each re-send this prompt.
    """
    if not (team_id and user_id and bot_token):
        return
    from .slack_client import SlackApiError, _call

    try:
        opened = _call("conversations.open", bot_token, users=user_id)
        dm_channel_id = opened["channel"]["id"]
        _call(
            "chat.postMessage",
            bot_token,
            channel=dm_channel_id,
            text="Upload your BIA/BCP here",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":open_file_folder: *Upload your BIA or BCP here* — just attach the file (DOCX, PDF or XLSX) to this chat, and I'll read it automatically.",
                    },
                }
            ],
        )
    except SlackApiError:
        logger.exception("Couldn't send the upload-prompt DM to %s for team %s", user_id, team_id)


def build_bia_upload_card(team_id: str, user_id: str = "", bot_token: str = "") -> dict:
    from plans.models import STATUS_FAILED, STATUS_PARSED

    plan = _latest_plan(team_id) if team_id else None

    if plan is None:
        # Rendered as a real image (sir's design) -- same template-code
        # approach as the other cards. Entirely static content, so
        # this is one cached image reused for everyone. The "Open DM"
        # (a real deep LINK) and "Check again" buttons stay real Slack
        # buttons underneath it. No separate HEADER block here -- the
        # image's own logo+badge already is the header.
        from django.conf import settings

        from .upload_status_card_image import get_upload_status_card_image_url

        image_url = get_upload_status_card_image_url(settings.BACKEND_URL)
        blocks = [{"type": "image", "image_url": image_url, "alt_text": "No file uploaded yet"}]
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":speech_balloon: Open DM with TestMyPlan", "emoji": True},
                        # Deep-links straight into the DM with THIS app --
                        # sir's call: removes the "what does DM mean, DM
                        # who?" confusion entirely instead of just
                        # explaining it better in text. team= is required,
                        # not optional -- without it, Slack opens whatever
                        # workspace happens to be active, which is the
                        # wrong one for anyone signed into multiple
                        # workspaces (confirmed live).
                        "url": _dm_redirect_url(team_id, user_id, bot_token),
                        "action_id": "v2_bia_open_app_dm",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    },
                ],
            }
        )
        # Moved out of the image per sir's reference design -- sits below
        # the real buttons, outside the card's own border.
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Takes 1-3 minutes once sent — this screen refreshes itself automatically, no need to keep clicking Check again.",
                    }
                ],
            }
        )
        return {"blocks": blocks}

    # Rendered as a real image (sir's design) -- same template-code
    # approach as the other cards. No separate HEADER block -- the
    # image's own logo+badge replaces it.
    from django.conf import settings

    from .bia_services_card_image import get_bia_services_card_image_url

    if plan.status == STATUS_FAILED:
        blocks = [HEADER]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":x: *{plan.filename}* couldn't be read.\n{plan.parse_error or 'Unknown error.'}\n\nSend a fresh copy as a DM to this app.",
                },
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    }
                ],
            }
        )
        return {"blocks": blocks}

    if plan.status != STATUS_PARSED:
        blocks = [HEADER]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":hourglass_flowing_sand: *{plan.filename}* is still being read…\n"
                        "_Usually takes 1-3 minutes. This screen updates itself automatically once it's ready — "
                        "no need to keep clicking Check again._"
                    ),
                },
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    }
                ],
            }
        )
        return {"blocks": blocks}

    # Parsed -- show the resilience map (RTO/RPO/Impacts) right here,
    # plus Approve / Make changes, instead of a separate "Continue to AI
    # Analysis" click into a second screen.
    # Critical Process sub-tab removed (sir's call) -- RTO is the only
    # view of this extracted BIA/BCP data now, so the tab row that used
    # to switch between the two no longer has anything to switch to.
    rows, overflow_count, found_text = _services_groups(plan)

    approved = plan.resilience_map_status == "approved"
    if approved:
        status_note = "Approved — this data is being used to rank your Threat Profile."
    elif plan.generation_source == "ai_draft":
        # An AI-generated draft has no real person's upload behind it --
        # the 10 onboarding questions ARE the confirmation step here,
        # not a plain Approve click (cards/draft_confirmation_modal_v2.py).
        status_note = "Confirm or correct it before it's used — 10 quick questions."
        count_match = re.search(r"\d+", found_text)
        if count_match:
            found_text = f"We drafted {count_match.group()} services for you"
    else:
        status_note = "Does this look right? Edit any RTO before you approve."

    is_ai_draft = (not approved) and plan.generation_source == "ai_draft"
    image_url = get_bia_services_card_image_url(
        settings.BACKEND_URL, plan.filename, found_text, rows, overflow_count, status_note, is_ai_draft=is_ai_draft
    )
    blocks = [{"type": "image", "image_url": image_url, "alt_text": "Services found with an RTO"}]

    if approved:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Want to change the file? Click here", "emoji": True},
                        "action_id": "v2_bia_refresh",
                        # Also opens the DM, not just a silent refresh --
                        # sir's call: a click that visibly does nothing
                        # (because nothing changed since last refresh)
                        # reads as a broken button, even though it worked.
                        "url": _dm_redirect_url(team_id, user_id, bot_token),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "→ Continue to Teams", "emoji": True},
                        "action_id": "v2_ai_approve",
                        "style": "primary",
                    },
                ],
            }
        )
    elif plan.generation_source == "ai_draft":
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Want to change the file? Click here", "emoji": True},
                        "action_id": "v2_bia_refresh",
                        "url": _dm_redirect_url(team_id, user_id, bot_token),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Review & confirm (10 questions)", "emoji": True},
                        "action_id": "v2_draft_review_open",
                        "style": "primary",
                    },
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Want to change the file? Click here", "emoji": True},
                        "action_id": "v2_bia_refresh",
                        "url": _dm_redirect_url(team_id, user_id, bot_token),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "↻ Check again", "emoji": True},
                        "action_id": "v2_bia_check_again",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":pencil2: Edit RTOs", "emoji": True},
                        "action_id": "v2_bia_edit_rtos",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Add service", "emoji": True},
                        "action_id": "v2_bia_add_service",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                        "action_id": "v2_ai_approve",
                        "style": "primary",
                    },
                ],
            }
        )
    return {"blocks": blocks}
