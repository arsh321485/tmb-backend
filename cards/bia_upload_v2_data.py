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

from django.conf import settings

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


def build_bia_question_card() -> dict:
    """First thing shown on this step, before any upload instructions
    (flowchart's "BCP/BIA available?" decision) -- Yes leads to the
    upload instructions below, No points at the GRC Department instead."""
    return {
        "blocks": [
            HEADER,
            {"type": "section", "text": {"type": "mrkdwn", "text": "Do you already have a BIA or BCP document ready?"}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes", "emoji": True}, "action_id": "v2_bia_have_doc_yes", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No", "emoji": True}, "action_id": "v2_bia_have_doc_no"},
                ],
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
                    "text": (
                        ":office: *Your GRC Department should prepare this first.*\n\n"
                        "Go to your organization's GRC department and ask them for a BIA or BCP document — "
                        "then come back here and upload it once it's ready."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "I have it now", "emoji": True},
                        "action_id": "v2_bia_have_doc_yes",
                        "style": "primary",
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Don't want to wait on GRC? We can generate a draft for you instead.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Generate a draft for us instead", "emoji": True},
                        "action_id": "v2_bia_generate_draft",
                    }
                ],
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
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":inbox_tray: *Draft request received for {org_name}.*\n"
                        f"Website on file: {website_url}\n\n"
                        "We'll let you know here once it's ready."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    }
                ],
            },
        ]
    }


def build_draft_failed_card(team_id: str) -> dict:
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
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Try again", "emoji": True},
                        "action_id": "v2_bia_generate_draft",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Want to change the file? Click here", "emoji": True},
                        "action_id": "v2_bia_refresh",
                        "url": f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}",
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
    blocks.append({"type": "divider"})
    for svc in services[:MAX_SERVICES_SHOWN]:
        name = svc.get("name") or "Unnamed service"
        rto = svc.get("rto") or "not stated"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{name}*\nRTO: `{rto}`"}})
    if len(services) > MAX_SERVICES_SHOWN:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"+ {len(services) - MAX_SERVICES_SHOWN} more, used in ranking but not shown here"}],
            }
        )
    return blocks


def build_bia_upload_card(team_id: str) -> dict:
    from plans.models import STATUS_FAILED, STATUS_PARSED

    plan = _latest_plan(team_id) if team_id else None

    blocks = [HEADER]

    if plan is None:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "No file uploaded yet.\n\n*Send your BIA or BCP document* (DOCX, PDF or XLSX) as a direct message "
                        "*to the TestMyPlan app itself* (not to a person) — tap the button below to open that chat, "
                        "then attach your file there.\n\n"
                        "_Once sent, it usually takes 1-3 minutes to process. This screen updates itself automatically "
                        "when it's ready — no need to keep clicking Check again._"
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
                        "text": {"type": "plain_text", "text": ":speech_balloon: Open DM with TestMyPlan", "emoji": True},
                        # Deep-links straight into the DM with THIS app --
                        # sir's call: removes the "what does DM mean, DM
                        # who?" confusion entirely instead of just
                        # explaining it better in text. team= is required,
                        # not optional -- without it, Slack opens whatever
                        # workspace happens to be active, which is the
                        # wrong one for anyone signed into multiple
                        # workspaces (confirmed live).
                        "url": f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}",
                        "action_id": "v2_bia_open_app_dm",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Check again", "emoji": True},
                        "action_id": "v2_bia_refresh",
                    },
                ],
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
                        "url": f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}",
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
                        "url": f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}",
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
                        "url": f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":pencil2: Edit RTOs", "emoji": True},
                        "action_id": "v2_bia_edit_rtos",
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
