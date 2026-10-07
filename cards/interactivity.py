"""
Routes Slack's "block_actions" and "view_submission" payloads that
aren't part of the new-design preview (see interactivity_v2.py for
that -- routed separately in cards/views.py by the "v2_" action_id
prefix).

The old command-center wizard that used to live here was deleted (sir's
call -- replaced by the new design). This file is now just the shared
plumbing real backend features still need: view_submission routing for
any modal that isn't v2-specific, and event/view dedup.
"""

import logging

import mongoengine

from cards import admin_invite_modal_v2, bulk_assign_modal_v2, org_setup_v2, team_copy_modal_v2, team_role_modal_v2
from home_tab.models import ProcessedSlackEvent
from workspaces.models import get_bot_token

logger = logging.getLogger(__name__)


def handle_block_action(payload: dict) -> None:
    """
    Nothing real routes here anymore -- the old wizard cards that used
    these action_ids are gone. Logged rather than silently dropped, in
    case a stale card from before the deletion is still sitting in
    someone's Slack and gets clicked.
    """
    actions = payload.get("actions") or []
    action_id = actions[0].get("action_id", "") if actions else ""
    logger.info("block_actions with no handler (old command-center card?): action_id=%s", action_id)


def handle_view_submission(payload: dict) -> None:
    view_id = payload.get("view", {}).get("id", "")
    # Confirmed live: submitting posted the confirmation twice. Same fix
    # as the Events API's retry dedup -- claim this exact view_id once;
    # a genuinely new modal open gets a fresh view_id, so this doesn't
    # block real re-submissions after fixing a validation error.
    if view_id and not _claim(f"view_submit:{view_id}"):
        return

    team_id = payload.get("team", {}).get("id", "")
    bot_token = get_bot_token(team_id)
    if not bot_token:
        return

    callback_id = payload.get("view", {}).get("callback_id", "")
    if callback_id == team_role_modal_v2.CALLBACK_ID:
        team_role_modal_v2.handle_submission(payload, bot_token)
    elif callback_id == admin_invite_modal_v2.CALLBACK_ID:
        admin_invite_modal_v2.handle_submission(payload, bot_token)
    elif callback_id == org_setup_v2.CALLBACK_ID:
        org_setup_v2.handle_submission(payload, bot_token)
    elif callback_id == bulk_assign_modal_v2.CALLBACK_ID:
        bulk_assign_modal_v2.handle_submission(payload, bot_token)
    elif callback_id == team_copy_modal_v2.CALLBACK_ID:
        team_copy_modal_v2.handle_submission(payload, bot_token)
    else:
        logger.info("view_submission with no handler: callback_id=%s", callback_id)


def _claim(key: str) -> bool:
    try:
        ProcessedSlackEvent(event_id=key).save(force_insert=True)
        return True
    except mongoengine.errors.NotUniqueError:
        return False
