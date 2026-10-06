"""
Click-through routing for the new-design preview cards (cards/blocks_v2/,
#testmyplan-command-center). Deliberately separate from interactivity.py --
nothing here can ever affect the real, live command-center flow. Every
action_id here is prefixed "v2_" so cards/views.py can tell the two
apart at a glance.

This is a design-review demo, not real backend logic: clicking through
just shows the next card in the new flow. No database writes, no real
state -- that's still pending sir's go/no-go decision on the design
itself before it's worth building for real.
"""

import json
import logging
from pathlib import Path

import requests

from workspaces.models import get_bot_token

from . import inject_modal_v2
from . import report_modal_v2
from . import team_role_modal_v2
from .admins_v2_data import build_admins_card
from .admins_v2_data import read_current_state as read_admins_state
from .nav_v2 import with_nav_bar_v2
from .slack_members_v2 import get_workspace_people
from .scenario_v2_data import build_scenario_card
from . import teams_v2_data
from .teams_v2_data import ADD_CUSTOM_ROLE_VALUE, build_teams_card
from .teams_v2_data import read_current_state as read_teams_state
from .test_plan_v2_data import build_test_plan_card
from .threat_map_v2_data import build_threat_map_card
from .threats_v2_data import build_org_threats_card, read_current_state
from .trigger_v2_data import build_live_card, build_trigger_card
from . import user_flow_test
from .user_nav_test import with_nav_bar_user_test
from . import persistence_v2
from . import admin_notify_v2

logger = logging.getLogger(__name__)

BLOCKS_V2_DIR = Path(__file__).parent / "blocks_v2"


def _load_v2_card(filename: str, **replacements) -> dict:
    text = (BLOCKS_V2_DIR / filename).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return json.loads(text)


def _replace_message(response_url: str, card: dict) -> None:
    requests.post(response_url, json={"replace_original": True, **card}, timeout=10)


def _redraw_threats(response_url: str, state: dict, slack_team_id: str = "") -> None:
    from . import org_setup_v2

    profile = org_setup_v2.load_profile(slack_team_id) if slack_team_id else None
    _replace_message(response_url, with_nav_bar_v2(build_org_threats_card(state, profile), "org_threats"))


def _redraw_admins(response_url: str, bot_token: str, current_user_id: str, state: dict) -> None:
    people = get_workspace_people(bot_token)
    _replace_message(response_url, with_nav_bar_v2(build_admins_card(state, people, current_user_id), "admins"))


def _redraw_teams(response_url: str, bot_token: str, state: dict) -> None:
    people = get_workspace_people(bot_token)
    _replace_message(response_url, with_nav_bar_v2(build_teams_card(state, people), "teams"))


def _redraw_map(response_url: str, module: str, expanded_threat: str = "", expanded_incident: str = "") -> None:
    card = build_threat_map_card(module, expanded_threat, expanded_incident)
    _replace_message(response_url, with_nav_bar_v2(card, "threat_map"))


def handle_block_action_v2(payload: dict) -> None:
    actions = payload.get("actions") or []
    if not actions:
        return
    action = actions[0]
    action_id = action.get("action_id", "")
    response_url = payload.get("response_url", "")
    message_blocks = payload.get("message", {}).get("blocks", [])
    slack_team_id = payload.get("team", {}).get("id", "")
    current_user_id = payload.get("user", {}).get("id", "")
    bot_token = get_bot_token(slack_team_id)

    if action_id == "v2_test_join_exercise":
        if response_url:
            _replace_message(response_url, {"blocks": with_nav_bar_user_test(user_flow_test._join_screen_body(), "join")})
        return

    if action_id == "v2_test_nav_jump__welcome":
        if response_url:
            _replace_message(response_url, {"blocks": with_nav_bar_user_test(user_flow_test._welcome_body(), "welcome")})
        return

    if action_id == "v2_test_nav_jump__join":
        if response_url:
            _replace_message(response_url, {"blocks": with_nav_bar_user_test(user_flow_test._join_screen_body(), "join")})
        return

    if action_id.startswith("v2_test_sitrep__"):
        channel_id = payload.get("channel", {}).get("id", "")
        label = action.get("text", {}).get("text", "")
        if channel_id and bot_token:
            user_flow_test.post_sitrep_ack(channel_id, bot_token, label)
            user_flow_test.post_decision_screen(channel_id, bot_token)
        return

    if action_id.startswith("v2_test_decision__"):
        channel_id = payload.get("channel", {}).get("id", "")
        choice = action.get("value", "")
        if channel_id and bot_token:
            user_flow_test.post_decision_reaction(channel_id, bot_token, choice)
        return

    if action_id == "v2_test_ack_confirm":
        channel_id = payload.get("channel", {}).get("id", "")
        if channel_id and bot_token:
            from workspaces.models import Workspace

            ws = Workspace.objects(team_id=slack_team_id).first()
            bridge_id = ws.privacy_bridge_channel_id if ws else ""
            user_flow_test.post_ack_reaction(channel_id, bot_token, bridge_id)
            if bridge_id:
                user_flow_test.post_privacy_bridge_opened(bridge_id, bot_token)
        return

    if action_id.startswith("v2_test_attest__"):
        channel_id = payload.get("channel", {}).get("id", "")
        choice = action.get("value", "")
        if channel_id and bot_token:
            user_flow_test.post_attest_reaction(channel_id, bot_token, choice)
        return

    if action_id == "v2_test_statement_approve":
        channel_id = payload.get("channel", {}).get("id", "")
        if channel_id and bot_token:
            user_flow_test.post_statement_approved(channel_id, bot_token)
        return

    if action_id == "v2_test_debrief_report":
        channel_id = payload.get("channel", {}).get("id", "")
        if channel_id and bot_token:
            user_flow_test.post_debrief_report_notice(channel_id, bot_token)
        return

    if action_id == "v2_test_show_assignments":
        channel_id = payload.get("channel", {}).get("id", "")
        if channel_id and bot_token:
            user_flow_test.post_show_assignments(channel_id, bot_token)
        return

    if action_id.startswith("v2_test_window__"):
        channel_id = payload.get("channel", {}).get("id", "")
        choice = action.get("value", "")
        if channel_id and bot_token:
            user_flow_test.post_window_picked(channel_id, bot_token, choice)
        return

    # "Get started" on Welcome -- goes straight to Admins. Organization
    # Details is no longer a Slack step at all (sir's call): it's captured
    # on the website signup form and saved to the real OrgProfile, just
    # never shown or editable inside Slack.
    if action_id == "v2_welcome_next":
        _redraw_admins(response_url, bot_token, current_user_id, persistence_v2.load_admins_state(slack_team_id))
        return

    if action_id == "v2_nav_jump__welcome":
        from .onboarding_v2 import welcome_card_replacements

        replacements = welcome_card_replacements(slack_team_id, current_user_id, bot_token)
        _replace_message(response_url, with_nav_bar_v2(_load_v2_card("01-welcome.json", **replacements), "welcome"))
        return
        return

    # A criticality dropdown changed on an existing (fixed or custom)
    # threat -- read everything else straight out of the message Slack
    # just sent us, apply this one change, save it for real, redraw with
    # fresh counts.
    if action_id == "v2_threat_crit_select":
        state = read_current_state(message_blocks)
        # CRITICAL: only the active module's threats are visible in the
        # message now (sub-tabs) -- reading just the message would wipe
        # the other module's saved criticalities, same class of bug as
        # the Teams card's tier tabs. Load the real saved ones first.
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        block_id = action.get("block_id", "")
        new_value = action.get("selected_option", {}).get("value", "")
        if block_id.startswith("threat_"):
            state["fixed"][block_id.removeprefix("threat_")] = new_value
        elif block_id.startswith("customthreat|"):
            _, module, label = block_id.split("|", 2)
            for c in state["custom"]:
                if c["module"] == module and c["label"] == label:
                    c["crit"] = new_value
        persistence_v2.save_threats_state(slack_team_id, state)
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_module_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_module"] = action.get("value", "Cybersecurity")
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_crit_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_crit"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_name_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_threat"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_incident_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_incident"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id)
        return

    # "+ Add a threat we missed" -- opens the inline form.
    if action_id == "v2_threat_add_open":
        state = read_current_state(message_blocks)
        state["form"] = {"module": None, "threat": None, "crit": None}
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_threat_add_module_select":
        state = read_current_state(message_blocks)
        new_module = action.get("selected_option", {}).get("value", "")
        # Changing the module resets the threat pick -- the previous
        # threat came from the OTHER module's catalog.
        state["form"] = {"module": new_module, "threat": None, "crit": (state.get("form") or {}).get("crit")}
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_threat_add_threat_select":
        state = read_current_state(message_blocks)
        value = action.get("selected_option", {}).get("value", "")
        form = state.get("form") or {}
        form["threat"] = None if value == "__none__" else value
        state["form"] = form
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_add_crit__"):
        state = read_current_state(message_blocks)
        form = state.get("form") or {}
        form["crit"] = action_id.removeprefix("v2_threat_add_crit__")
        state["form"] = form
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_threat_add_confirm":
        state = read_current_state(message_blocks)
        # Same reasoning as v2_threat_crit_select above.
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        form = state.get("form") or {}
        if form.get("module") and form.get("threat") and form.get("crit"):
            # Slack requires every block_id in a message to be unique, and
            # each custom threat's block_id is built from (module, label)
            # -- a duplicate (e.g. from a double-click/double-fire) would
            # silently break every future render of that tab. Guard it here.
            already_exists = any(
                c["module"] == form["module"] and c["label"] == form["threat"] for c in state["custom"]
            )
            if not already_exists:
                state["custom"].append({"module": form["module"], "label": form["threat"], "crit": form["crit"]})
        state["form"] = None
        persistence_v2.save_threats_state(slack_team_id, state)
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_threat_add_cancel":
        state = read_current_state(message_blocks)
        state["form"] = None
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_pick_cause__"):
        # Sir's call: fold the old separate "Threat map" step's incident/
        # cause drill-down into the Threat Profile card directly (same
        # taxonomy, just shown here) -- clicking a cause goes straight
        # into picking its scenario, no separate step in between.
        module, threat_id, incident_id, cause_id = action.get("value", "").split(":", 3)
        persistence_v2.save_scenario_selection(
            slack_team_id, module, threat_id=threat_id, incident_id=incident_id, cause_id=cause_id, scenario_id=""
        )
        card = build_scenario_card(module, threat_id, incident_id, cause_id)
        _replace_message(response_url, with_nav_bar_v2(card, "org_threats"))
        return

    if action_id == "v2_nav_jump__org_threats":
        state = persistence_v2.load_threats_state(slack_team_id)
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_nav_jump__admins":
        _redraw_admins(response_url, bot_token, current_user_id, persistence_v2.load_admins_state(slack_team_id))
        return

    if action_id == "v2_admin_take_all":
        state = read_admins_state(message_blocks)
        for mod in ("cyber", "privacy"):
            state["assigned"][mod] = current_user_id
        state["expanded"] = None
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id == "v2_admin_assign_open":
        state = read_admins_state(message_blocks)
        state["expanded"] = action.get("value", "")
        state["delegate_pick"] = None
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id == "v2_admin_pick_self":
        state = read_admins_state(message_blocks)
        mod_id = action.get("value", "")
        state["assigned"][mod_id] = current_user_id
        state["expanded"] = None
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id.startswith("v2_admin_pick_person__"):
        state = read_admins_state(message_blocks)
        mod_id, _, code = action.get("value", "").partition(":")
        if mod_id and code:
            state["assigned"][mod_id] = code
            admin_notify_v2.send_admin_assigned_dm(slack_team_id, mod_id, code, bot_token)
        state["expanded"] = None
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    # "+ Invite by email" -- real modal (Full name + email). Honest
    # limitation: a bot can't send Slack workspace invites (confirmed
    # live), so this only records the intended admin -- the human admin
    # still invites them into Slack via Slack's own screen.
    if action_id == "v2_admin_invite_email":
        from . import admin_invite_modal_v2
        from .admins_v2_data import MODULE_ADMINS

        mod_id = action.get("value", "")
        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        module_label = next((m["m"] for m in MODULE_ADMINS if m["id"] == mod_id), mod_id)
        if trigger_id and channel_id and message_ts and bot_token:
            admin_invite_modal_v2.open_modal(trigger_id, mod_id, channel_id, message_ts, module_label, bot_token)
        return

    if action_id == "v2_admin_cancel":
        state = read_admins_state(message_blocks)
        state["expanded"] = None
        state["delegate_pick"] = None
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id == "v2_admin_overflow":
        state = read_admins_state(message_blocks)
        value = action.get("selected_option", {}).get("value", "")
        mod_id, _, sub_action = value.partition(":")
        if sub_action == "remove":
            state["assigned"].pop(mod_id, None)
        elif sub_action == "change":
            state["assigned"].pop(mod_id, None)
            state["expanded"] = mod_id
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    # "Continue — set up response teams" -- advances to Step 3.
    if action_id == "v2_admins_done":
        _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id))
        return

    if action_id == "v2_nav_jump__teams":
        _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id))
        return

    if action_id == "v2_team_add_open":
        state = read_teams_state(message_blocks)
        state["add"] = {"team_id": action.get("value", ""), "role": None, "primary": [], "backup": []}
        _redraw_teams(response_url, bot_token, state)
        return

    def _open_custom_text_modal(field: str, state: dict) -> None:
        slack_team_id = payload.get("team", {}).get("id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        trigger_id = payload.get("trigger_id", "")
        bot_token = get_bot_token(slack_team_id)
        target = state.get("add") or state.get("map") or {}
        team_id = target.get("team_id", "")
        if trigger_id and channel_id and message_ts and bot_token:
            team_role_modal_v2.open_modal(
                trigger_id, field, team_id, channel_id, message_ts,
                state["teams"], state.get("resp", {}), state.get("add"), state.get("map"), bot_token,
            )

    if action_id == "v2_team_role_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        add = state.get("add") or {}

        if selected == ADD_CUSTOM_ROLE_VALUE:
            # Free text needs a real modal -- Slack buttons/selects can't
            # take arbitrary typed input.
            _open_custom_text_modal("role", state)
            return

        add["role"] = selected
        state["add"] = add
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_member_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        add = state.get("add") or {}
        add["primary"] = [selected] if selected and selected != "__none__" else []
        # A person just made the member can't also still be their own backup.
        add["backup"] = [c for c in add.get("backup", []) if c != selected]
        state["add"] = add
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_backup_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        add = state.get("add") or {}
        add["backup"] = [selected] if selected and selected != "__none__" else []
        state["add"] = add
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_role_confirm":
        state = read_teams_state(message_blocks)
        # CRITICAL: the visible message only ever shows ONE team's members
        # at a time (every other team is collapsed) -- saving state["teams"]
        # as read straight from the message would silently wipe every other
        # team's already-saved members. Load the real saved data first.
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        add = state.get("add") or {}
        team_id = add.get("team_id", "")
        if team_id and add.get("role") and add.get("primary") and add.get("backup"):
            state["teams"].setdefault(team_id, [])
            state["teams"][team_id].append(
                {"role": add["role"], "primary": add["primary"], "backup": add["backup"]}
            )
            # Sir's call: don't make the admin map a responsibility by hand
            # for every member -- each catalog role already has one default
            # test action, so fill it in immediately.
            # Real per-team responsibility from sir's spreadsheet -- keyed
            # by (team_id, role) since the same role name can carry a
            # different responsibility on a different team. Falls back to
            # the old generic 8-role guess only for a role that isn't in
            # the spreadsheet (e.g. a free-typed custom role).
            from .team_catalog_v2 import default_responsibility_for

            default_resp = default_responsibility_for(team_id, add["role"]) or teams_v2_data.ROLE_DEFAULT_RESP.get(add["role"])
            if default_resp:
                state["resp"].setdefault(team_id, [])
                state["resp"][team_id].append({"who": add["role"], **default_resp})
            state["add"] = None
            persistence_v2.save_teams_state(slack_team_id, state["teams"], state["resp"])

            # Let the assigned person know right away -- previously nobody
            # was ever told they'd been put on a team.
            from .team_catalog_v2 import find_team
            from .team_assignment_notify_v2 import send_team_assignment_dm

            team_info = find_team(team_id)
            team_name = team_info["name"] if team_info else team_id
            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            primary_id = add["primary"][0]
            backup_id = add["backup"][0] if add["backup"] else ""
            send_team_assignment_dm(
                slack_team_id, team_name, add["role"], primary_id, backup_id, default_resp, by_code, bot_token,
            )
        # If required fields are missing, leave the form open as-is
        # rather than silently discarding what's already picked.
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_add_cancel":
        state = read_teams_state(message_blocks)
        state["add"] = None
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_member_overflow":
        state = read_teams_state(message_blocks)
        # Same reasoning as v2_team_role_confirm above -- load the real
        # saved teams/resp before mutating and saving, so removing one
        # member doesn't wipe every other team's saved members.
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        value = action.get("selected_option", {}).get("value", "")
        team_id, _, rest = value.partition(":")
        index_str, _, sub_action = rest.partition(":")
        if sub_action == "remove":
            try:
                index = int(index_str)
                del state["teams"][team_id][index]
                state["dm_open"].discard(f"{team_id}:{index_str}")
                persistence_v2.save_teams_state(slack_team_id, state["teams"], state["resp"])
            except (ValueError, IndexError, KeyError):
                pass
        elif sub_action == "view":
            dm_key = f"{team_id}:{index_str}"
            if dm_key in state["dm_open"]:
                state["dm_open"].discard(dm_key)
            else:
                state["dm_open"].add(dm_key)
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_team_map_responsibilities":
        # Same reasoning as the tier/expand fixes above -- the visible
        # message never carries a team's already-mapped responsibilities
        # outside of this exact flow, so reading the message alone always
        # looked empty even when the real mapping was already saved.
        message_state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state = {**message_state, "teams": saved["teams"], "resp": saved["resp"]}
        state["map"] = {
            "team_id": action.get("value", ""), "text": None, "who": None,
            "action": None, "detail": None, "phase": "Containment",
        }
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_resp_text_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        if selected == ADD_CUSTOM_RESP_VALUE:
            _open_custom_text_modal("resp", state)
            return
        map_state = state.get("map") or {}
        map_state["text"] = selected
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id.startswith("v2_resp_who_toggle__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        map_state["who"] = action.get("value", "")
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id.startswith("v2_resp_action_pick__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        # Picking a new action type invalidates whatever exact-action
        # was chosen -- that list is specific to the previous type.
        map_state["action"] = action.get("value", "")
        map_state["detail"] = None
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_resp_detail_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        if selected == "__add_custom_detail__":
            _open_custom_text_modal("detail", state)
            return
        map_state = state.get("map") or {}
        map_state["detail"] = selected
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id.startswith("v2_resp_phase_pick__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        map_state["phase"] = action.get("value", "")
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_resp_map_confirm":
        state = read_teams_state(message_blocks)
        # Same reasoning as v2_team_role_confirm above.
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        map_state = state.get("map") or {}
        team_id = map_state.get("team_id", "")
        if team_id and map_state.get("text") and map_state.get("who") and map_state.get("action") and map_state.get("detail"):
            state["resp"].setdefault(team_id, [])
            state["resp"][team_id].append(
                {
                    "text": map_state["text"], "who": map_state["who"], "action": map_state["action"],
                    "detail": map_state["detail"], "phase": map_state.get("phase") or "Containment",
                }
            )
            # Ready for the next one -- same team, blank pick, matching
            # the mockup's own reset-after-add behavior.
            state["map"] = {"team_id": team_id, "text": None, "who": None, "action": None, "detail": None, "phase": "Containment"}
            persistence_v2.save_teams_state(slack_team_id, state["teams"], state["resp"])
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_resp_map_done":
        state = read_teams_state(message_blocks)
        state["map"] = None
        _redraw_teams(response_url, bot_token, state)
        return

    if action_id == "v2_resp_map_remove":
        state = read_teams_state(message_blocks)
        # Same reasoning as v2_team_role_confirm above.
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        team_id, _, index_str = action.get("value", "").partition(":")
        try:
            index = int(index_str)
            del state["resp"][team_id][index]
            persistence_v2.save_teams_state(slack_team_id, state["teams"], state["resp"])
        except (ValueError, IndexError, KeyError):
            pass
        _redraw_teams(response_url, bot_token, state)
        return

    # Tier tab switch (Mandatory/Recommended/Optional/External).
    if action_id.startswith("v2_team_tier__"):
        # A collapsed team's members are only ever rendered into the message
        # while it's expanded -- reading the message alone would wipe every
        # other team's data back to "unstaffed" the moment you switch tabs.
        # Pull the real teams/responsibilities from the DB instead; only
        # things that live purely in the message (the in-progress add/map
        # flow, dm_open) still come from there.
        message_state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state = {**message_state, "teams": saved["teams"], "resp": saved["resp"]}
        state["active_tier"] = action.get("value", "Mandatory")
        state["expanded_team"] = None
        _redraw_teams(response_url, bot_token, state)
        return

    # Expand/collapse one team's detail + members + add-member flow.
    if action_id == "v2_team_expand_toggle":
        # Same reasoning as the tier switch above -- load real team data
        # from the DB so opening/closing a team never loses another team's
        # already-saved members.
        message_state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state = {**message_state, "teams": saved["teams"], "resp": saved["resp"]}
        value = action.get("value", "")
        state["expanded_team"] = None if value == "__none__" else (value or None)
        _redraw_teams(response_url, bot_token, state)
        return

    # "Teams ready" -- advances to Threats (new order: Teams -> Threats -> Threat map).
    if action_id == "v2_teams_done":
        state = persistence_v2.load_threats_state(slack_team_id)
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_nav_jump__threat_map":
        _redraw_map(response_url, "Cybersecurity")
        return

    if action_id.startswith("v2_map_jump__"):
        module, _, threat_id = action.get("value", "").partition(":")
        _redraw_map(response_url, module, threat_id)
        return

    if action_id.startswith("v2_map_module__"):
        _redraw_map(response_url, action.get("value", ""))
        return

    if action_id.startswith("v2_map_expand_threat__"):
        module, _, threat_id = action.get("value", "").partition(":")
        _redraw_map(response_url, module, threat_id)
        return

    if action_id.startswith("v2_map_expand_incident__"):
        module, threat_id, incident_id = action.get("value", "").split(":")
        _redraw_map(response_url, module, threat_id, incident_id)
        return

    if action_id.startswith("v2_map_pick_scenario__"):
        module, threat_id, incident_id, cause_id, scenario = action.get("value", "").split(":", 4)
        # Save the drill-down path as soon as a cause is picked -- so even
        # if nobody finishes picking an exact scenario yet, we don't lose
        # how far they got.
        persistence_v2.save_scenario_selection(
            slack_team_id, module, threat_id=threat_id, incident_id=incident_id, cause_id=cause_id, scenario_id=""
        )
        card = build_scenario_card(module, threat_id, incident_id, cause_id)
        _replace_message(response_url, with_nav_bar_v2(card, "threat_map"))
        return

    if action_id.startswith("v2_scenario_pick__"):
        module, threat_id, incident_id, cause_id, scenario = action.get("value", "").split(":", 4)
        persistence_v2.save_scenario_selection(
            slack_team_id, module, threat_id=threat_id, incident_id=incident_id, cause_id=cause_id, scenario_id=scenario
        )
        card = build_scenario_card(module, threat_id, incident_id, cause_id, selected=scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "org_threats"))
        return

    if action_id == "v2_scenario_done":
        module, _, scenario = action.get("value", "").partition(":")
        if not scenario:
            return  # nothing picked yet -- button isn't primary/active in that case
        card = build_test_plan_card(module, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))
        return

    if action_id == "v2_plan_arm":
        module, _, scenario = action.get("value", "").partition(":")
        import datetime

        persistence_v2.save_scenario_selection(
            slack_team_id, module, scenario_id=scenario, armed=True, armed_at=datetime.datetime.utcnow()
        )
        card = build_trigger_card(module, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id.startswith("v2_trigger_pick__"):
        module, scenario, trigger_key = action.get("value", "").split(":", 2)
        slack_team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(slack_team_id)
        from .trigger_v2_data import TRIGGER_LABELS

        # Step 1 -- a real Exercise record, replacing the old mock "Live"
        # screen that didn't create or save anything.
        from exercises.models import Exercise
        from workspaces.models import Workspace

        exercise = Exercise(
            scenario_name=scenario,
            module=module,
            trigger_type=trigger_key,
            started_by_slack_user_id=current_user_id,
            slack_team_id=slack_team_id,
        )

        workspace = Workspace.objects(team_id=slack_team_id).first()
        # Step 2 -- the real alarm goes into the real war-room/privacy-bridge
        # channel, not the admin's own command-center channel.
        target_channel_id = ""
        if workspace:
            target_channel_id = (
                workspace.privacy_bridge_channel_id if module == "Privacy" else workspace.ir_war_room_channel_id
            ) or ""
        exercise.slack_channel_id = target_channel_id
        exercise.save()

        if target_channel_id and bot_token:
            alarm_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: Incident detected", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{scenario}*"}},
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"{TRIGGER_LABELS.get(trigger_key, trigger_key)} · this is a TestMyPlan readiness drill — do not action externally."}
                    ],
                },
            ]
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "channel": target_channel_id,
                    "text": f"Incident detected — {scenario}",  # fallback for notifications
                    "blocks": alarm_blocks,
                },
                timeout=10,
            )

        # Step 3 -- DM every real staffed team member their job, using the
        # real Team/TeamMember data from Card 4. Previously nobody was
        # ever notified when a drill "started."
        if bot_token:
            from exercises.drill import send_drill_tasks

            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            send_drill_tasks(exercise, bot_token, by_code)

        card = build_live_card(module, scenario, trigger_key, exercise=exercise)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id == "v2_drill_task_done":
        # Step 4 -- the stopwatch actually stopping. Real timestamp, real
        # elapsed time, saved for the report.
        import datetime

        from exercises.models import ExerciseTask

        task_id = action.get("value", "")
        task = ExerciseTask.objects(id=task_id).first()
        if task and task.status == "sent":
            task.status = "done"
            task.responded_at = datetime.datetime.utcnow()
            task.save()
            elapsed = task.responded_at - task.sent_at
            minutes = int(elapsed.total_seconds() // 60)
            seconds = int(elapsed.total_seconds() % 60)
            _replace_message(
                response_url,
                {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":white_check_mark: *Done* — {task.role} on {task.team_name}\nRecorded in {minutes}m {seconds}s.",
                            },
                        }
                    ]
                },
            )

            # Step 6 -- once every real task for this drill has either
            # been done or escalated (nothing left "sent"), the exercise
            # is over; the report can now show a completed drill instead
            # of one that looks stuck mid-run forever.
            exercise = task.exercise
            if exercise and not ExerciseTask.objects(exercise=exercise, status="sent"):
                exercise.status = "completed"
                exercise.ended_at = datetime.datetime.utcnow()
                exercise.save()
        return

    if action_id == "v2_live_inject":
        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        slack_team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(slack_team_id)
        if trigger_id and channel_id and bot_token:
            inject_modal_v2.open_modal(trigger_id, channel_id, bot_token)
        return

    if action_id.startswith("v2_inject_send__"):
        index = int(action_id.removeprefix("v2_inject_send__"))
        view = payload.get("view", {})
        channel_id = view.get("private_metadata", "")
        view_id = view.get("id", "")
        slack_team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(slack_team_id)
        if channel_id and view_id and bot_token:
            inject_modal_v2.send_inject(index, channel_id, view_id, bot_token)
        return

    if action_id == "v2_live_report":
        trigger_id = payload.get("trigger_id", "")
        slack_team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(slack_team_id)
        if trigger_id and bot_token:
            report_modal_v2.open_modal(trigger_id, bot_token, slack_team_id)
        return

    if action_id.startswith("v2_nav_jump__"):
        # Nav tabs for steps not built yet -- nothing to show, leave the
        # current card as-is rather than erroring or going blank.
        return
