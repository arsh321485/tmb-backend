"""
"No BCP, generate a draft" path -- the confirmation step sir finalized
as 10 questions (trimmed from the 30-Minute Contextual Onboarding doc's
16). A real client document skips this (the uploaded file IS the
confirmation); an AI-generated draft (plans/draft_generation.py) must
go through this before it counts as approved, since nothing in it has
been confirmed by a real person yet.

One modal, not a multi-tab card flow -- Slack MESSAGES cap at 50 blocks
(see bia_upload_v2_data.py's MAX_SERVICES_SHOWN comment) but a modal
VIEW allows up to 100, which comfortably fits the research summary plus
all 10 questions without needing tabs.

Tolerance bands match sir's finalized answer formats exactly:
  outage tolerance: 4h / 8h / 24h / 72h / 1 week
  data-loss tolerance: None / 15 min / 1h / 24h
"""

import json
import logging

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_draft_confirmation_modal"

OUTAGE_BANDS = ["4h", "8h", "24h", "72h", "1 week"]
DATA_LOSS_BANDS = ["None", "15 min", "1h", "24h"]

# Max services shown with full tolerance pickers -- a modal allows 100
# blocks total and each service costs 2, so this stays well inside that
# even with the other ~20 fixed blocks around it.
MAX_SERVICES_IN_MODAL = 8


import re

# Hour-value for each band, used to pick the nearest one numerically --
# NOT by substring match. A naive "is '4' in the text" match (the
# original version of this function) matched "4h" against "24 hours"
# too, since "24 hours" literally contains the character "4" -- live-
# tested and confirmed every service silently collapsed to "4h"
# regardless of its real proposed value because of this.
_OUTAGE_BAND_HOURS = {"4h": 4, "8h": 8, "24h": 24, "72h": 72, "1 week": 168}
_DATA_LOSS_BAND_HOURS = {"None": 0, "15 min": 0.25, "1h": 1, "24h": 24}


def _parse_hours(text: str) -> float | None:
    """Best-effort parse of free text ("4 hours", "immediate", "near
    zero", "1 week") into hours. None if it can't be read at all."""
    t = (text or "").lower()
    if "immediate" in t or "near zero" in t or "real-time" in t or "real time" in t:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|hr|h\b|day|days|week|weeks|minute|minutes|min\b)", t)
    if not match:
        return None
    value, unit = match.groups()
    value = float(value)
    if unit.startswith("day"):
        value *= 24
    elif unit.startswith("week"):
        value *= 168
    elif unit.startswith("min"):
        value /= 60
    return value


def _nearest_band(value: str, bands: list, band_hours: dict) -> str:
    """The AI's proposed_rto/rpo is free text (e.g. "4 hours"); map it
    to the closest fixed band sir's question format allows -- the
    smallest band whose hour value is still >= the real value, so a
    tight requirement never silently relaxes to a looser default."""
    hours = _parse_hours(value)
    if hours is None:
        return bands[0]
    for band in bands:
        if band_hours[band] >= hours:
            return band
    return bands[-1]


def _summary_text(plan) -> str:
    items = plan.draft_research_items or []
    lines = []
    for i in items[:10]:  # keep well under the block's own text-length limits
        val = (i.get("value") or "")[:200]
        lines.append(f"*{i.get('id', '')} {i.get('title', '')}:* {val}")
    if len(items) > 10:
        lines.append(f"_+ {len(items) - 10} more research items not shown here._")
    return "\n\n".join(lines) or "No research summary available."


def build_modal_view(plan, channel_id: str = "", message_ts: str = "") -> dict:
    services = (plan.resilience_map or {}).get("candidate_services_full") or []
    services = services[:MAX_SERVICES_IN_MODAL]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "1. Is the researched profile correct?", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _summary_text(plan)}},
        {
            "type": "input",
            "block_id": "q1_edits",
            "optional": True,
            "label": {"type": "plain_text", "text": "Anything to fix? (leave blank to accept as-is)"},
            "element": {"type": "plain_text_input", "action_id": "value", "multiline": True},
        },
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": "2-4. Critical services & tolerances", "emoji": True}},
        {
            "type": "input",
            "block_id": "q2_services",
            "optional": True,
            "label": {"type": "plain_text", "text": "Which services would hurt most if stopped? (top 3-5)"},
            "element": {
                "type": "checkboxes",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": s.get("service", "")[:75]}, "value": s.get("service", "")}
                    for s in services
                ],
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Every service below still needs its own recovery time, even the ones you don't check above "
                        "-- checking a box just flags it as a TOP priority, it doesn't skip the others._"
                    ),
                }
            ],
        },
    ]

    for idx, s in enumerate(services):
        name = s.get("service", "")[:60]
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{name}*"}]})
        blocks.append(
            {
                "type": "input",
                "block_id": f"q3_outage__{idx}",
                "label": {"type": "plain_text", "text": "How long before an outage is unacceptable?"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": (outage_default := _nearest_band(s.get("proposed_rto", ""), OUTAGE_BANDS, _OUTAGE_BAND_HOURS))},
                        "value": outage_default,
                    },
                    "options": [{"text": {"type": "plain_text", "text": b}, "value": b} for b in OUTAGE_BANDS],
                },
            }
        )
        blocks.append(
            {
                "type": "input",
                "block_id": f"q4_dataloss__{idx}",
                "label": {"type": "plain_text", "text": "How much data could you afford to lose?"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": (dataloss_default := _nearest_band(s.get("proposed_rpo", ""), DATA_LOSS_BANDS, _DATA_LOSS_BAND_HOURS))},
                        "value": dataloss_default,
                    },
                    "options": [{"text": {"type": "plain_text", "text": b}, "value": b} for b in DATA_LOSS_BANDS],
                },
            }
        )

    blocks += [
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": "5-6. Decision authority", "emoji": True}},
        {
            "type": "input",
            "block_id": "q5_role",
            "label": {"type": "plain_text", "text": "Who can authorise shutting down a critical system?"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "q5_isolate",
            "label": {"type": "plain_text", "text": "May the IR lead isolate without approval?"},
            "element": {
                "type": "radio_buttons",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": "Yes"}, "value": "yes"},
                    {"text": {"type": "plain_text", "text": "No"}, "value": "no"},
                ],
            },
        },
        {
            "type": "input",
            "block_id": "q6_regulators",
            "label": {"type": "plain_text", "text": "Who speaks to regulators?"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "q6_customers",
            "label": {"type": "plain_text", "text": "Who speaks to customers?"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "q6_media",
            "label": {"type": "plain_text", "text": "Who speaks to media?"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": "7-9. Technology & monitoring", "emoji": True}},
        {
            "type": "input",
            "block_id": "q7_edits",
            "optional": True,
            "label": {"type": "plain_text", "text": "Identity platform & hosting -- anything to fix? (blank = correct as researched)"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {
            "type": "input",
            "block_id": "q7_ot",
            "label": {"type": "plain_text", "text": "Any OT or building systems on the network?"},
            "element": {
                "type": "radio_buttons",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": "Yes"}, "value": "yes"},
                    {"text": {"type": "plain_text", "text": "No"}, "value": "no"},
                ],
            },
        },
        {
            "type": "input",
            "block_id": "q8_backups",
            "label": {"type": "plain_text", "text": "Do you have offline/immutable backups?"},
            "element": {
                "type": "radio_buttons",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": "Yes"}, "value": "yes"},
                    {"text": {"type": "plain_text", "text": "No"}, "value": "no"},
                    {"text": {"type": "plain_text", "text": "Unsure"}, "value": "unsure"},
                ],
            },
        },
        {
            "type": "input",
            "block_id": "q9_monitoring",
            "label": {"type": "plain_text", "text": "Who monitors your environment 24/7?"},
            "element": {
                "type": "radio_buttons",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": "In-house"}, "value": "in-house"},
                    {"text": {"type": "plain_text", "text": "MSSP"}, "value": "mssp"},
                    {"text": {"type": "plain_text", "text": "None"}, "value": "none"},
                ],
            },
        },
        {
            "type": "input",
            "block_id": "q9_mssp_name",
            "optional": True,
            "label": {"type": "plain_text", "text": "If MSSP, which one?"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
        {"type": "divider"},
        {"type": "header", "text": {"type": "plain_text", "text": "10. Incident history", "emoji": True}},
        {
            "type": "input",
            "block_id": "q10_incidents",
            "label": {"type": "plain_text", "text": "Any significant incidents or near misses in the last 3 years?"},
            "element": {
                "type": "radio_buttons",
                "action_id": "value",
                "options": [
                    {"text": {"type": "plain_text", "text": "Yes"}, "value": "yes"},
                    {"text": {"type": "plain_text", "text": "No"}, "value": "no"},
                ],
            },
        },
        {
            "type": "input",
            "block_id": "q10_detail",
            "optional": True,
            "label": {"type": "plain_text", "text": "If yes, one line:"},
            "element": {"type": "plain_text_input", "action_id": "value"},
        },
    ]

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"plan_id": str(plan.id), "channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Confirm your draft"},
        "submit": {"type": "plain_text", "text": "Confirm & finish"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def open_modal(trigger_id: str, plan, bot_token: str, channel_id: str = "", message_ts: str = "") -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(plan, channel_id, message_ts)},
        timeout=10,
    )


def _text_value(values: dict, block_id: str) -> str:
    return (values.get(block_id, {}).get("value", {}).get("value") or "").strip()


def _radio_value(values: dict, block_id: str) -> str:
    opt = values.get(block_id, {}).get("value", {}).get("selected_option")
    return (opt or {}).get("value", "")


def _select_value(values: dict, block_id: str) -> str:
    opt = values.get(block_id, {}).get("value", {}).get("selected_option")
    return (opt or {}).get("value", "")


def handle_submission(payload: dict, bot_token: str) -> None:
    from .nav_v2 import with_nav_bar_v2
    from .persistence_v2 import load_teams_state, save_teams_card_location
    from .slack_client import SlackApiError, _call
    from .teams_v2_data import build_teams_card
    from .slack_members_v2 import get_workspace_people
    from plans.models import Plan

    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        return
    plan = Plan.objects(id=meta.get("plan_id", "")).first() if meta.get("plan_id") else None
    if not plan:
        return

    values = view.get("state", {}).get("values", {})
    services = (plan.resilience_map or {}).get("candidate_services_full") or []
    services = services[:MAX_SERVICES_IN_MODAL]
    selected_names = {
        o.get("value")
        for o in (values.get("q2_services", {}).get("value", {}).get("selected_options") or [])
    }

    confirmed_services = []
    for idx, s in enumerate(services):
        name = s.get("service", "")
        confirmed_services.append(
            {
                "name": name,
                "rto": _select_value(values, f"q3_outage__{idx}") or s.get("proposed_rto", ""),
                "rpo": _select_value(values, f"q4_dataloss__{idx}") or s.get("proposed_rpo", ""),
                "flagged_critical": name in selected_names,
                "source": "Client-confirmed (onboarding questions)",
            }
        )

    answers = {
        "q1_profile_edits": _text_value(values, "q1_edits"),
        "q5_shutdown_authority": _text_value(values, "q5_role"),
        "q5_isolate_without_approval": _radio_value(values, "q5_isolate"),
        "q6_speaks_to_regulators": _text_value(values, "q6_regulators"),
        "q6_speaks_to_customers": _text_value(values, "q6_customers"),
        "q6_speaks_to_media": _text_value(values, "q6_media"),
        "q7_identity_hosting_edits": _text_value(values, "q7_edits"),
        "q7_ot_on_network": _radio_value(values, "q7_ot"),
        "q8_offline_backups": _radio_value(values, "q8_backups"),
        "q9_monitoring": _radio_value(values, "q9_monitoring"),
        "q9_mssp_name": _text_value(values, "q9_mssp_name"),
        "q10_prior_incidents": _radio_value(values, "q10_incidents"),
        "q10_prior_incidents_detail": _text_value(values, "q10_detail"),
    }

    rm = dict(plan.resilience_map or {})
    rm["services"] = confirmed_services
    rm["client_confirmation"] = answers
    plan.resilience_map = rm
    # Answering these questions IS the confirmation -- an AI draft has no
    # separate upload/Approve step a real person already did, so this
    # submission is what "approved" means for this plan.
    plan.resilience_map_status = "approved"
    plan.save()

    team_id = plan.slack_team_id
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    if team_id and channel_id and message_ts:
        try:
            people = get_workspace_people(bot_token)
            card = with_nav_bar_v2(
                build_teams_card(load_teams_state(team_id), people, slack_team_id=team_id), "teams"
            )
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
            save_teams_card_location(team_id, channel_id, message_ts)
        except SlackApiError:
            logger.exception("Couldn't push Teams card after draft confirmation for team %s", team_id)
        except Exception:
            # The answers above are already saved by this point (plan.save()
            # happened before this block) -- a failure here only means the
            # live screen refresh didn't happen, not that anything was lost.
            logger.exception("Unexpected error pushing Teams card after draft confirmation for team %s", team_id)
