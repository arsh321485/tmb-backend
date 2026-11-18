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
    upload instructions below, No points at the GRC Department instead."""
    return {
        "blocks": [
            HEADER,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "We'll extract your RTOs, critical services, and build your threat landscape straight from your real document.",
                },
            },
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": ":page_facing_up: *Do you already have a BIA or BCP document ready?*"}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": ":white_check_mark: Yes, I have it", "emoji": True}, "action_id": "v2_bia_have_doc_yes", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": ":no_entry_sign: Not yet", "emoji": True}, "action_id": "v2_bia_have_doc_no"},
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":bulb: No document yet? No problem — we'll point you to your next best option."}],
            },
        ]
    }


def build_grc_department_card() -> dict:
    """The "No" answer -- flowchart routes this to the GRC Department to
    prepare the document first, rather than to the upload instructions.
    Also offers a second, faster option (sir's call): generate a draft
    ourselves instead of GRC's ~4 week turnaround, for a client who
    doesn't want to wait or pay extra for that."""
    return {
        "blocks": [
            HEADER,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "No document yet? No problem — pick whichever path fits you best:",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": ":office: *Option A · GRC Department*\n_Thorough, done by your own team_"},
                    {"type": "mrkdwn", "text": ":zap: *Option B · Generate for me*\n_Fast, researched automatically_"},
                ],
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": ":hourglass_flowing_sand: ~4 weeks turnaround"},
                    {"type": "mrkdwn", "text": ":stopwatch: Ready in minutes"},
                ],
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "Ask your GRC department for a real BIA or BCP document, then come back and upload it."},
                    {"type": "mrkdwn", "text": "We research your organization and draft a starting BIA/BCP for you to confirm."},
                ],
            },
            {"type": "divider"},
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
    asked again here) and that the request is recorded."""
    from .models_v2 import OrgProfile

    profile = OrgProfile.objects(team_id=team_id).first() if team_id else None
    org_name = (profile.org_name if profile else "") or "your organization"
    website_url = (profile.website_url if profile else "") or "not on file"

    return {
        "blocks": [
            HEADER,
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":inbox_tray: *Draft request received for {org_name}.*"},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":globe_with_meridians: Website on file: {website_url}"}],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":hourglass_flowing_sand: Researching now — usually takes 2-4 minutes. This screen updates itself automatically when it's ready."}],
            },
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


def _services_blocks(plan) -> list:
    from plans.threat_ranking import _rto_to_hours

    services = (plan.resilience_map or {}).get("services") or []
    blocks = []

    if not services:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "The AI didn't find any named services/processes with recovery objectives in this document."},
            }
        )
        return blocks

    # Sir's call: shortest RTO (most urgent) first, not whatever order
    # the document happened to list them in. A service with no readable
    # RTO sorts last, not first -- it shouldn't look more urgent than
    # one that actually has a real number just because it's unreadable.
    def _sort_key(svc: dict) -> float:
        hours = _rto_to_hours(svc.get("rto") or "")
        return hours if hours is not None else float("inf")

    services = sorted(services, key=_sort_key)

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"Found *{len(services)}* service(s) with an RTO:"}})
    # Separated by category (Service / Technology / Application) instead
    # of one flat list -- a BIA/BCP document genuinely distinguishes a
    # business process from the infrastructure or named software it
    # depends on, and lumping all three together made that distinction
    # disappear. Order within each group stays most-urgent-first.
    shown_total = 0
    remaining_budget = MAX_SERVICES_SHOWN
    for category, header in (("Service", "Services"), ("Technology", "Technology"), ("Application", "Applications")):
        group = [s for s in services if (s.get("category") or "Service") == category]
        if not group:
            continue

        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{header}*"}})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*Name*"},
                    {"type": "mrkdwn", "text": "*RTO*"},
                ],
            }
        )
        shown_group = group[:remaining_budget]
        remaining_budget -= len(shown_group)
        shown_total += len(shown_group)
        for i, svc in enumerate(shown_group, 1):
            name = svc.get("name") or "Unnamed item"
            rto = svc.get("rto") or "not stated"
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*{i}.*  *{name}*"},
                        {"type": "mrkdwn", "text": f"`{rto}`"},
                    ],
                }
            )

    if len(services) > shown_total:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"+ {len(services) - shown_total} more, used in ranking but not shown here"}],
            }
        )
    return blocks


def build_bia_upload_card(team_id: str, user_id: str = "", bot_token: str = "") -> dict:
    from plans.models import STATUS_FAILED, STATUS_PARSED

    plan = _latest_plan(team_id) if team_id else None

    blocks = [HEADER]

    if plan is None:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_circle: *No file uploaded yet*"}],
            }
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Send your BIA or BCP document* as a direct message *to the TestMyPlan app itself* (not to a person) — tap the button below to open that chat, then attach your file there.",
                },
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":page_facing_up: DOCX   ·   :page_facing_up: PDF   ·   :bar_chart: XLSX"}],
            }
        )
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
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":hourglass_flowing_sand: Takes 1-3 minutes once sent — this screen refreshes itself automatically, no need to keep clicking Check again."}],
            }
        )
        return {"blocks": blocks}

    if plan.status == STATUS_FAILED:
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
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":white_check_mark: *{plan.filename}* uploaded and read successfully."},
        }
    )
    blocks.append({"type": "divider"})
    # Critical Process sub-tab removed (sir's call) -- RTO is the only
    # view of this extracted BIA/BCP data now, so the tab row that used
    # to switch between the two no longer has anything to switch to.
    blocks.extend(_services_blocks(plan))
    blocks.append({"type": "divider"})

    approved = plan.resilience_map_status == "approved"
    if approved:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Approved* — this data is being used to rank your Threat Profile."}],
            }
        )
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
        # An AI-generated draft has no real person's upload behind it --
        # the 10 onboarding questions ARE the confirmation step here,
        # not a plain Approve click (cards/draft_confirmation_modal_v2.py).
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "This is a researched draft, not a document you uploaded. Please confirm or correct it before it's used.",
                },
            }
        )
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
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "Does this look right?"}})
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
