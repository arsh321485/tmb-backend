"""
"Does this look right?" on Upload & Analysis -- lets the admin correct
a wrong RTO the AI extraction got wrong from a real uploaded document,
instead of only being able to accept-or-reject the whole thing.

Separate from cards/draft_confirmation_modal_v2.py's tolerance-band
pickers -- that one is for the AI-generated-draft path (sir's fixed
4h/8h/24h/... bands, matching the 10-question flow). This one edits a
real uploaded document's real extracted RTOs, which are free text
("3 days", "1 month", whatever the document actually says), so a plain
text field is the right input here, not a fixed band picker.
"""

import json
import logging

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_edit_rtos_modal"

# Modal views allow up to 100 blocks; one input block per service keeps
# this comfortably inside that even for an org with many services.
MAX_SERVICES_IN_MODAL = 40


def _sorted_services(plan) -> list:
    """Shortest RTO (most urgent) first -- same order and same sort key
    as bia_upload_v2_data.py's _services_blocks, so the list the admin
    sees here matches what they saw on the main screen. Used by BOTH
    build_modal_view and handle_submission so the two stay in the same
    order -- handle_submission matches edited values back to services
    by index, so a mismatch here would silently save the wrong RTO
    against the wrong service."""
    from plans.threat_ranking import _rto_to_hours

    services = (plan.resilience_map or {}).get("services") or []

    def _sort_key(svc: dict) -> float:
        hours = _rto_to_hours(svc.get("rto") or "")
        return hours if hours is not None else float("inf")

    return sorted(services, key=_sort_key)


def build_modal_view(plan, channel_id: str = "", message_ts: str = "") -> dict:
    services = _sorted_services(plan)
    services = services[:MAX_SERVICES_IN_MODAL]

    blocks = []
    for idx, svc in enumerate(services):
        name = (svc.get("name") or "Unnamed service")[:150]
        blocks.append(
            {
                "type": "input",
                "block_id": f"rto__{idx}",
                "optional": True,
                "label": {"type": "plain_text", "text": name[:75] or "Service"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "initial_value": (svc.get("rto") or "")[:150],
                    "placeholder": {"type": "plain_text", "text": "e.g. 4 hours, 2 days, 1 week"},
                },
            }
        )

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"plan_id": str(plan.id), "channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Edit RTOs"},
        "submit": {"type": "plain_text", "text": "Save"},
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


def handle_submission(payload: dict, bot_token: str) -> None:
    from .bia_upload_v2_data import build_bia_upload_card
    from .nav_v2 import with_nav_bar_v2
    from .slack_client import SlackApiError, _call
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
    all_services = _sorted_services(plan)
    shown_services = all_services[:MAX_SERVICES_IN_MODAL]
    # Anything beyond the modal's own cap was never shown/editable --
    # keep it as-is rather than silently dropping it on save.
    remainder_services = all_services[MAX_SERVICES_IN_MODAL:]

    edited_services = []
    for idx, svc in enumerate(shown_services):
        new_rto = (values.get(f"rto__{idx}", {}).get("value", {}).get("value") or "").strip()
        edited = dict(svc)
        if new_rto:
            edited["rto"] = new_rto
            edited["source"] = "Edited by admin"
        edited_services.append(edited)

    rm = dict(plan.resilience_map or {})
    rm["services"] = edited_services + remainder_services
    plan.resilience_map = rm
    plan.save()

    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    if channel_id and message_ts and bot_token:
        try:
            card = with_nav_bar_v2(build_bia_upload_card(plan.slack_team_id), "bia_upload")
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
        except SlackApiError:
            logger.exception("Couldn't refresh Upload & Analysis card after RTO edit for team %s", plan.slack_team_id)
        except Exception:
            logger.exception("Unexpected error refreshing Upload & Analysis card after RTO edit for team %s", plan.slack_team_id)
