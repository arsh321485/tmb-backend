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

from accounts.models import User
from cards.loader import load_card
from cards.models import get_or_create_state
from cards.nav import card_file_for_nav_key, nav_key_for_card_file, with_nav_bar
from cards.render import build_admin_team_card
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
    "bia_upload": "07-bia-ready.json",
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

    # "Add Priya" etc -- actually persist the addition (WizardState) and
    # re-render the admin team card reflecting it, instead of a no-op.
    if action_id == "admin_add":
        person_code = actions[0].get("value", "")
        state = get_or_create_state(team_id)
        if person_code and person_code not in state.admins_added:
            state.admins_added.append(person_code)
            state.save()

        workspace = Workspace.objects(team_id=team_id).first()
        org_name = workspace.team_name if workspace else ""
        card = build_admin_team_card(team_id, org_name=org_name)
        card = with_nav_bar(card, "admin")
        _replace_message(response_url, card)
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
    else:
        card = load_card(next_card_file, org_name=org_name, person_name=person_name)

    nav_key = nav_key_for_card_file(next_card_file)
    if nav_key:
        card = with_nav_bar(card, nav_key)

    _replace_message(response_url, card)


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
