"""
Routes Slack's "block_actions" payloads (sent when someone clicks a
button/select/checkbox in one of our cards) to whatever should happen
next -- posting the next card in the flow described in
slack_cards/README.md's card map.

Clicking replaces the message in place (via Slack's response_url) rather
than posting a new one each time, so re-clicking a button doesn't pile up
duplicate cards.

This wires the main linear setup wizard (Welcome -> Admin team ->
Response teams -> Threat map -> BIA -> Scenario -> Test plan -> Trigger
-> Live). It's a scripted walkthrough, not yet backed by real state --
"Add Priya" doesn't actually add a real person anywhere yet, and every
"pick a threat/scenario" path leads to the same next card regardless of
which one was clicked. Real per-org team/scenario data is separate,
larger work (would extend the accounts/exercises/plans models).
"""

import logging

import requests

import mongoengine

from accounts.models import User
from cards.create_team_modal import handle_add_member_click, handle_submission, open_modal
from cards import upload_bia_modal
from cards.loader import load_card
from cards.models import get_or_create_state
from cards.nav import card_file_for_nav_key, nav_key_for_card_file, with_nav_bar
from cards.render import build_admin_team_card, build_response_teams_card, build_threat_map_card
from home_tab.models import ProcessedSlackEvent
from workspaces.models import Workspace, get_bot_token

logger = logging.getLogger(__name__)

# action_id -> next card to show. None entries just acknowledge the click
# (e.g. picking a radio option) without changing the card.
_ADVANCE_MAP = {
    "welcome_build_admin": "02-admin-team.json",
    "admin_add": None,
    "admin_done": "03-response-teams.json",
    "team_add": None,
    "team_add_all": None,
    "team_create": None,
    "teams_done": "05-threat-map.json",
    "threat_jump": "06-bia-needed.json",
    "threat_module": None,
    "threat_scenarios": "06-bia-needed.json",
    "threat_open": "06-bia-needed.json",
    # bia_upload handled specially below -- no longer a fake instant "success".
    "bia_scenarios": "08-scenario.json",
    "scenario_select": None,
    "scenario_plan": "09-test-plan.json",
    "plan_arm": "10-trigger.json",
    "trigger_now": "11-test-live.json",
    "trigger_sched": "11-test-live.json",
    "trigger_surprise": "11-test-live.json",
    "live_report": "23-preparedness-report.json",
    "live_new": "01-welcome.json",
    "role_ack": None,
}


def handle_block_action(payload: dict) -> None:
    team_id = payload.get("team", {}).get("id", "")
    slack_user_id = payload.get("user", {}).get("id", "")
    response_url = payload.get("response_url", "")

    actions = payload.get("actions") or []
    if not actions:
        return

    action_id = actions[0].get("action_id", "")

    # "+ Add member" inside the Create a team modal -- redraws the modal
    # with that role/member pair added, doesn't submit or touch the channel.
    if action_id == "modal_add_member":
        bot_token = get_bot_token(team_id)
        if bot_token:
            handle_add_member_click(payload, bot_token)
        return

    # "Create a team" -- opens a real Slack modal (see create_team_modal.py)
    # instead of another chat card, since it needs actual form inputs.
    if action_id == "team_create":
        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        if trigger_id and bot_token:
            open_modal(trigger_id, channel_id, bot_token)
        return

    # Admin team card: expand a person to choose their module, change that
    # choice, confirm (commits to WizardState), cancel (discards), or
    # remove an already-confirmed admin. All of these just redraw the same
    # card differently -- nothing except "confirm"/"remove" is saved.
    if action_id == "admin_expand":
        _redraw_admin_card(team_id, response_url, expanded_code=actions[0].get("value", ""))
        return

    if action_id.startswith("admin_pick_module__"):
        code, _, module = actions[0].get("value", "").partition(":")
        _redraw_admin_card(team_id, response_url, expanded_code=code, selected_module=module)
        return

    if action_id == "admin_confirm":
        code, _, module = actions[0].get("value", "").partition(":")
        if code:
            state = get_or_create_state(team_id)
            state.admin_modules[code] = module
            state.save()
        _redraw_admin_card(team_id, response_url)
        return

    if action_id == "admin_cancel":
        _redraw_admin_card(team_id, response_url)
        return

    # "Continue -- set up response teams": post a permanent summary of who
    # was confirmed before moving on, so that decision isn't just lost when
    # the card gets replaced by the next step (also doubles as an audit
    # trail, per the tracker's "immutable transcript" requirement).
    if action_id == "admin_done":
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        if channel_id and bot_token:
            _post_admin_summary(team_id, channel_id, bot_token)

    if action_id == "admin_add":
        # The confirmed-admin row's own button: "✓ Admin -- click to remove".
        person_code = actions[0].get("value", "")
        if person_code:
            state = get_or_create_state(team_id)
            state.admin_modules.pop(person_code, None)
            state.save()
        _redraw_admin_card(team_id, response_url)
        return

    # Confirmed-admin row's "..." overflow menu -- "Change module" re-opens
    # the same expanded picker (prefilled with their current module) instead
    # of forcing Remove-then-re-add just to switch someone's module.
    if action_id == "admin_overflow":
        value = actions[0].get("selected_option", {}).get("value", "")
        code, _, act = value.partition(":")
        if not code:
            return
        state = get_or_create_state(team_id)
        if act == "remove":
            state.admin_modules.pop(code, None)
            state.save()
            _redraw_admin_card(team_id, response_url)
        elif act == "change":
            current_module = state.admin_modules.get(code, "All modules")
            _redraw_admin_card(team_id, response_url, expanded_code=code, selected_module=current_module)
        return

    # Response teams card: "Add Sofia" etc. toggles that person's real
    # notified/added status (same self-correcting pattern as admin_add).
    # Can't send a genuine DM though -- these are the same mock names as
    # the admin list, not real Slack accounts.
    if action_id == "team_add":
        *_rest, code = actions[0].get("value", "").split(":")
        state = get_or_create_state(team_id)
        if code:
            if code in state.response_members_added:
                state.response_members_added.remove(code)
            else:
                state.response_members_added.append(code)
            state.save()
        _redraw_response_card(team_id, response_url)
        return

    if action_id == "team_add_all":
        from cards.render import RESPONSE_TEAMS

        state = get_or_create_state(team_id)
        all_codes = [m["code"] for t in RESPONSE_TEAMS for m in t["members"]]
        state.response_members_added = all_codes
        state.save()
        _redraw_response_card(team_id, response_url)
        return

    if action_id == "teams_done":
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        if channel_id and bot_token:
            _post_response_team_summary(team_id, channel_id, bot_token)

    # Threat map: sequential drill-down (category -> cause -> sub-cause ->
    # scenario), each click redrawing the card one level deeper. Slack
    # can't do a true accordion (several sections expanded at once, as the
    # design shows) -- this expands one thing at a time, same mechanism as
    # the admin-team card. Context (which module/category/cause) is
    # threaded through each button's value rather than stored, since it's
    # just navigation state, not something worth persisting.
    if action_id.startswith("threat_module__"):
        module = actions[0].get("value", "")
        card = build_threat_map_card(module=module)
        card = with_nav_bar(card, "threat")
        _replace_message(response_url, card)
        return

    if action_id.startswith("threat_jump__"):
        module, _, category_key = actions[0].get("value", "").partition(":")
        card = build_threat_map_card(module=module, expanded_category=category_key)
        card = with_nav_bar(card, "threat")
        _replace_message(response_url, card)
        return

    if action_id.startswith("threat_expand_category__"):
        module, _, category_key = actions[0].get("value", "").partition(":")
        card = build_threat_map_card(module=module, expanded_category=category_key)
        card = with_nav_bar(card, "threat")
        _replace_message(response_url, card)
        return

    if action_id.startswith("threat_expand_cause__"):
        module, category_key, cause_key = actions[0].get("value", "").split(":")
        card = build_threat_map_card(module=module, expanded_category=category_key, expanded_cause=cause_key)
        card = with_nav_bar(card, "threat")
        _replace_message(response_url, card)
        return

    if action_id.startswith("threat_scenarios__"):
        # The final pick -- post a permanent record of what was chosen
        # (same audit-trail pattern as the admin/response-team summaries),
        # then advance to Upload BIA.
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        value = actions[0].get("value", "")
        if channel_id and bot_token:
            _post_threat_scenario_summary(value, channel_id, bot_token)

        workspace = Workspace.objects(team_id=team_id).first()
        org_name = workspace.team_name if workspace else ""
        card = load_card("06-bia-needed.json", org_name=org_name)
        card = with_nav_bar(card, "bia")
        _replace_message(response_url, card)
        return

    # "Upload BIA" -- previously jumped straight to a fake "success" card
    # with a fictional filename. Then it posted a "drop your file in this
    # channel" instruction and waited for a message event. Now it opens a
    # real Slack modal with a native file picker (file_input) so clicking
    # the button goes straight to choosing a file, no separate drag/drop
    # step (see upload_bia_modal.py; parsing still goes through the real
    # plan intake pipeline, B1/B2).
    if action_id == "bia_upload":
        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        if trigger_id and bot_token:
            upload_bia_modal.open_modal(trigger_id, channel_id, bot_token)
        return

    # "Inject a scenario" -- was a single button that did nothing real.
    # Now a real dropdown (static_select) of specific scenarios; picking
    # one posts a real confirmation to the channel. Slack keeps the
    # dropdown showing the picked option on its own, so no card redraw
    # is needed here.
    if action_id == "live_inject_select":
        option = actions[0].get("selected_option", {})
        label = option.get("text", {}).get("text", "")
        channel_id = payload.get("channel", {}).get("id", "")
        bot_token = get_bot_token(team_id)
        if label and channel_id and bot_token:
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel_id, "text": f":zap: Injected: *{label}*"},
                timeout=10,
            )
        return

    # The nav bar (see nav.py) -- jump straight to any of the 5 main steps,
    # not just move forward one at a time.
    if action_id.startswith("nav_jump__"):
        target_key = actions[0].get("value", "")
        next_card_file = card_file_for_nav_key(target_key)
        if next_card_file is None:
            return
    else:
        # Some cards have several buttons that used to share one action_id
        # (invalid in Slack -- see the "invalid_blocks" fix) and now look
        # like "threat_jump__continuity_infra". Match on the part before
        # "__" so they still route the same way regardless of which
        # option was picked.
        lookup_id = action_id.split("__", 1)[0]

        if lookup_id not in _ADVANCE_MAP:
            logger.info("No handler wired yet for action_id=%s", action_id)
            return

        next_card_file = _ADVANCE_MAP[lookup_id]
        if next_card_file is None:
            return  # acknowledged, nothing to change on screen

    workspace = Workspace.objects(team_id=team_id).first()
    user = User.objects(slack_account__slack_user_id=slack_user_id).first()
    org_name = workspace.team_name if workspace else ""
    person_name = user.name if user else ""

    if next_card_file == "02-admin-team.json":
        card = build_admin_team_card(team_id, org_name=org_name, person_name=person_name)
    elif next_card_file == "03-response-teams.json":
        card = build_response_teams_card(team_id, org_name=org_name)
    elif next_card_file == "05-threat-map.json":
        card = build_threat_map_card()
    else:
        card = load_card(next_card_file, org_name=org_name, person_name=person_name)

    nav_key = nav_key_for_card_file(next_card_file)
    if nav_key:
        card = with_nav_bar(card, nav_key)

    _replace_message(response_url, card)


def _post_admin_summary(team_id: str, channel_id: str, bot_token: str) -> None:
    from cards.render import PEOPLE

    state = get_or_create_state(team_id)
    if not state.admin_modules:
        return

    names_by_code = {p["code"]: p["name"] for p in PEOPLE}
    lines = "\n".join(
        f"• *{names_by_code.get(code, code)}* added to the admin team -- _{module}_"
        for code, module in state.admin_modules.items()
    )
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "text": f":white_check_mark: Admin team confirmed:\n{lines}"},
        timeout=10,
    )


def _redraw_admin_card(team_id: str, response_url: str, expanded_code: str = "", selected_module: str = "") -> None:
    workspace = Workspace.objects(team_id=team_id).first()
    org_name = workspace.team_name if workspace else ""
    card = build_admin_team_card(
        team_id, org_name=org_name, expanded_code=expanded_code, selected_module=selected_module
    )
    card = with_nav_bar(card, "admin")
    _replace_message(response_url, card)


def _redraw_response_card(team_id: str, response_url: str) -> None:
    workspace = Workspace.objects(team_id=team_id).first()
    org_name = workspace.team_name if workspace else ""
    card = build_response_teams_card(team_id, org_name=org_name)
    card = with_nav_bar(card, "teams")
    _replace_message(response_url, card)


def _post_response_team_summary(team_id: str, channel_id: str, bot_token: str) -> None:
    from cards.render import RESPONSE_TEAMS

    state = get_or_create_state(team_id)
    if not state.response_members_added:
        return

    added = set(state.response_members_added)
    names_by_code = {
        m["code"]: (m["name"], m["role"]) for t in RESPONSE_TEAMS for m in t["members"]
    }
    lines = "\n".join(
        f"• *{names_by_code[code][0]}* -- {names_by_code[code][1]}"
        for code in added
        if code in names_by_code
    )
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "text": f":shield: Response teams confirmed:\n{lines}"},
        timeout=10,
    )


def _post_threat_scenario_summary(value: str, channel_id: str, bot_token: str) -> None:
    from cards.render import _find_cause

    try:
        module, category_key, cause_key, subcause_key = value.split(":")
    except ValueError:
        return

    cause = _find_cause(module, category_key, cause_key)
    if not cause:
        return

    subcause = next((s for s in cause["subcauses"] if s["key"] == subcause_key), None)
    focus = f"{cause['label']}" + (f" → {subcause['label']}" if subcause else "")

    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "text": f":dart: Focus set: {focus}"},
        timeout=10,
    )


def handle_view_submission(payload: dict) -> None:
    """Routes by callback_id -- more than one modal can submit now (Create
    team, Upload BIA)."""
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
    if callback_id == upload_bia_modal.CALLBACK_ID:
        upload_bia_modal.handle_submission(payload, team_id, bot_token)
    else:
        handle_submission(payload, bot_token)


def _claim(key: str) -> bool:
    try:
        ProcessedSlackEvent(event_id=key).save(force_insert=True)
        return True
    except mongoengine.errors.NotUniqueError:
        return False


def _replace_message(response_url: str, card: dict) -> None:
    """
    Posting back to response_url replaces the specific message whose
    button was clicked, instead of adding a new message underneath it.
    """
    if not response_url:
        return

    payload = dict(card)
    payload["replace_original"] = True
    payload.setdefault("text", "TestMyPlan")

    resp = requests.post(response_url, json=payload, timeout=10)
    if not resp.ok:
        logger.warning("response_url replace failed: %s %s", resp.status_code, resp.text)
