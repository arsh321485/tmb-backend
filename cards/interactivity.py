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

from cards import admin_invite_modal_v2, bulk_assign_modal_v2, org_setup_v2, team_copy_modal_v2, team_role_modal_v2, trigger_schedule_modal_v2
from home_tab.models import ProcessedSlackEvent
from workspaces.models import get_bot_token

logger = logging.getLogger(__name__)


def handle_block_action(payload: dict) -> None:
    """
    Real backend features that aren't part of the new-design preview
    route here, by exact action_id.
    """
    actions = payload.get("actions") or []
    action_id = actions[0].get("action_id", "") if actions else ""
    action = actions[0] if actions else {}

    if action_id == "resmap_confirm":
        from plans.models import Plan
        from plans.resilience_gaps import find_resilience_gaps, other_resilience_maps_for_team
        from cards.resilience_map_v2 import update_card, send_gaps_card, send_objectives_card

        plan_id = action.get("value", "")
        team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        plan = Plan.objects(id=plan_id).first() if plan_id else None
        if plan:
            plan.resilience_map_status = "approved"
            plan.save()
            update_card(plan, channel_id, message_ts, bot_token)

            # A11 -- if there's anything to flag, show it next; if the
            # map is already clean, skip straight to A12.
            other_plans = other_resilience_maps_for_team(team_id, exclude_plan_id=plan.id)
            gaps = find_resilience_gaps(plan.resilience_map or {}, other_plans=other_plans)
            if gaps:
                send_gaps_card(plan, channel_id, bot_token)
            else:
                send_objectives_card(plan, channel_id, bot_token)
        return

    if action_id == "resmap_gap_accept":
        from plans.models import Plan
        from plans.resilience_gaps import find_resilience_gaps, other_resilience_maps_for_team
        from cards.resilience_map_v2 import update_gaps_card, send_objectives_card

        value = action.get("value", "")
        plan_id, _, key = value.partition("|")
        team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        plan = Plan.objects(id=plan_id).first() if plan_id else None
        if plan and key:
            if key not in plan.accepted_gaps:
                plan.accepted_gaps.append(key)
                plan.save()
            update_gaps_card(plan, channel_id, message_ts, bot_token)

            # Once every flagged gap is accepted, move on to A12
            # automatically -- the owner shouldn't have to go looking
            # for the next step themselves.
            other_plans = other_resilience_maps_for_team(team_id, exclude_plan_id=plan.id)
            gaps = find_resilience_gaps(plan.resilience_map or {}, other_plans=other_plans)
            all_keys = {f"{g['service']}|{g['issue']}" for g in gaps}
            if all_keys and all_keys.issubset(set(plan.accepted_gaps)):
                send_objectives_card(plan, channel_id, bot_token)
        return

    if action_id == "resmap_gap_accept_all":
        from plans.models import Plan
        from plans.resilience_gaps import find_resilience_gaps, other_resilience_maps_for_team
        from cards.resilience_map_v2 import update_gaps_card, send_objectives_card

        plan_id = action.get("value", "")
        team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        plan = Plan.objects(id=plan_id).first() if plan_id else None
        if plan:
            other_plans = other_resilience_maps_for_team(team_id, exclude_plan_id=plan.id)
            gaps = find_resilience_gaps(plan.resilience_map or {}, other_plans=other_plans)
            all_keys = {f"{g['service']}|{g['issue']}" for g in gaps}
            newly_accepted = all_keys - set(plan.accepted_gaps or [])
            if newly_accepted:
                plan.accepted_gaps.extend(newly_accepted)
                plan.save()
            update_gaps_card(plan, channel_id, message_ts, bot_token)
            send_objectives_card(plan, channel_id, bot_token)
        return

    if action_id == "resmap_gap_noop":
        return

    if action_id == "resmap_retry":
        from plans.models import Plan
        from plans.resilience_map import extract_resilience_map
        from cards.resilience_map_v2 import send_card, update_retry_card

        plan_id = action.get("value", "")
        team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        plan = Plan.objects(id=plan_id).first() if plan_id else None
        if plan:
            resilience_map = extract_resilience_map(plan.extracted_text)
            if resilience_map:
                plan.resilience_map = resilience_map
                plan.resilience_map_status = "proposed"
                plan.save()
                send_card(plan, channel_id, bot_token)
            else:
                # Still no luck -- leave the retry button up so they
                # can try again rather than dead-ending them.
                update_retry_card(plan, channel_id, message_ts, bot_token)
        return

    if action_id == "resmap_objectives_lock":
        from plans.models import Plan
        from cards.resilience_map_v2 import update_objectives_card

        plan_id = action.get("value", "")
        team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        plan = Plan.objects(id=plan_id).first() if plan_id else None
        if plan:
            plan.objectives_register_status = "approved"
            plan.save()
            update_objectives_card(plan, channel_id, message_ts, bot_token)
        return

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
    elif callback_id == trigger_schedule_modal_v2.CALLBACK_ID:
        trigger_schedule_modal_v2.handle_submission(payload, bot_token)
    else:
        logger.info("view_submission with no handler: callback_id=%s", callback_id)


def _claim(key: str) -> bool:
    try:
        ProcessedSlackEvent(event_id=key).save(force_insert=True)
        return True
    except mongoengine.errors.NotUniqueError:
        return False
