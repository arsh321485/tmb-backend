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
from .bia_upload_v2_data import build_bia_upload_card
from .nav_v2 import with_nav_bar_v2
from .slack_members_v2 import get_workspace_people
from .scenario_v2_data import build_scenario_card
from . import teams_v2_data
from .teams_v2_data import ADD_CUSTOM_ROLE_VALUE, build_teams_card
from .teams_v2_data import read_current_state as read_teams_state
from .test_plan_v2_data import build_real_test_plan_card, build_test_plan_card
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
    # response_url posts return HTTP 200 with either a plain "ok" text
    # body OR a JSON {"ok": true} body (Slack is inconsistent about
    # which) even when the card itself is rejected (e.g. invalid_blocks)
    # -- that rejection was previously silent, so a bad card just looked
    # like "the button does nothing". Log it, but only for an actual
    # failure -- treating {"ok": true} as a failure (string != "ok") was
    # itself a bug, logging false warnings on successful updates.
    resp = requests.post(response_url, json={"replace_original": True, **card}, timeout=10)
    body = (resp.text or "").strip()
    if body in ("ok", ""):
        return
    try:
        if json.loads(body).get("ok") is True:
            return
    except (ValueError, AttributeError):
        pass
    logger.warning("response_url post was not accepted (status=%s): %s", resp.status_code, body[:500])


def _redraw_threats(response_url: str, state: dict, slack_team_id: str = "") -> None:
    from . import org_setup_v2

    if slack_team_id:
        # Real persistence for the drill-down position (which Module/
        # Criticality/Threat/Incident/Cause/Phase/Scenario tab is open) --
        # previously purely reconstructed from the Slack message, so it
        # reset to blank on every nav jump / fresh load. Restore it here
        # if the caller didn't already set it (e.g. coming straight from
        # persistence_v2.load_threats_state, which has no nav fields at
        # all), and save whatever the state ends up being after this click.
        saved_nav = persistence_v2.load_threat_profile_nav(slack_team_id)
        for field in persistence_v2.NAV_FIELDS:
            if field not in state:
                state[field] = saved_nav.get(field)

        # Phase/Scenario default to Identification/Trigger the first time a
        # (module, threat, incident, cause) combo is reached -- the card
        # builder mutates this set in place the moment it defaults one, so
        # it has to be read BEFORE building the card and saved AFTER, not
        # alongside the nav fields above.
        state["visited_combos"] = persistence_v2.load_visited_combos(slack_team_id)

    profile = org_setup_v2.load_profile(slack_team_id) if slack_team_id else None
    card = build_org_threats_card(state, profile, team_id=slack_team_id)

    if slack_team_id:
        persistence_v2.save_threat_profile_nav(slack_team_id, state)
        persistence_v2.save_visited_combos(slack_team_id, state["visited_combos"])

    _replace_message(response_url, with_nav_bar_v2(card, "org_threats"))


def _breadcrumb_from_nav(nav: dict) -> dict:
    """Turns the saved threat_profile_nav ids back into display labels --
    same lookup v2_nav_jump__test_plan already does, factored out so the
    Configure Test phase/scenario tab clicks (which only have the nav,
    not the full Threat Profile message) can show the same breadcrumb."""
    from .threat_map_v2_data import _find_threat
    from .threats_v2_data import THREATS

    active_module = nav.get("active_module")
    raw_key = nav.get("active_threat")
    threat_label = next((t["label"] for t in THREATS if t["key"] == raw_key), raw_key)
    incident_name, cause_name = nav.get("active_incident"), nav.get("active_cause")
    taxonomy_threat = _find_threat(active_module, raw_key) if active_module and raw_key else None
    if taxonomy_threat:
        incident = next((inc for inc in taxonomy_threat["incidents"] if inc["id"] == nav.get("active_incident")), None)
        if incident:
            incident_name = incident["name"]
            cause = next((c for c in incident["causes"] if c["id"] == nav.get("active_cause")), None)
            if cause:
                cause_name = cause["name"]
    return {
        "module": active_module, "crit": nav.get("active_crit"), "threat": threat_label,
        "incident": incident_name, "cause": cause_name,
    }


def _redraw_admins(response_url: str, bot_token: str, current_user_id: str, state: dict) -> None:
    people = get_workspace_people(bot_token)
    _replace_message(response_url, with_nav_bar_v2(build_admins_card(state, people, current_user_id), "admins"))


def _redraw_bia_upload(response_url: str, slack_team_id: str, channel_id: str = "", message_ts: str = "") -> None:
    _replace_message(response_url, with_nav_bar_v2(build_bia_upload_card(slack_team_id), "bia_upload"))
    if slack_team_id and channel_id and message_ts:
        persistence_v2.save_bia_upload_card_location(slack_team_id, channel_id, message_ts)


def _redraw_teams(response_url: str, bot_token: str, state: dict, slack_team_id: str = "", channel_id: str = "", message_ts: str = "") -> None:
    people = get_workspace_people(bot_token)
    _replace_message(response_url, with_nav_bar_v2(build_teams_card(state, people, slack_team_id=slack_team_id), "teams"))
    if slack_team_id and channel_id and message_ts:
        persistence_v2.save_teams_card_location(slack_team_id, channel_id, message_ts)


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
    top_channel_id = payload.get("channel", {}).get("id", "")
    top_message_ts = payload.get("message", {}).get("ts", "")

    if action_id.startswith("v2_tc_module_tab__") or action_id.startswith("v2_tc_crit_tab__") or action_id.startswith("v2_tc_threat_tab__"):
        from .threats_center_v2 import build_threats_center_card, read_current_state as read_tc_state

        state = read_tc_state(message_blocks)
        if action_id.startswith("v2_tc_module_tab__"):
            state["active_module"] = action_id.removeprefix("v2_tc_module_tab__")
            state["active_crit"] = None
            state["active_threat"] = None
        elif action_id.startswith("v2_tc_crit_tab__"):
            state["active_crit"] = action.get("value", "")
            state["active_threat"] = None
        else:
            state["active_threat"] = action.get("value", "")
        if response_url:
            _replace_message(response_url, build_threats_center_card(state, team_id=slack_team_id))
        return

    if action_id == "v2_tc_launch":
        from . import org_setup_v2
        from .threats_v2_data import build_org_threats_card

        value = action.get("value", "")
        active_module, active_crit, active_threat = (value.split("|", 2) + ["", "", ""])[:3]
        nav = {
            "active_module": active_module or None, "active_crit": active_crit or None,
            "active_threat": active_threat or None, "active_incident": None, "active_cause": None,
            "active_phase": None, "active_scenario": None,
        }
        if slack_team_id:
            persistence_v2.save_threat_profile_nav(slack_team_id, nav)
        profile = org_setup_v2.load_profile(slack_team_id) if slack_team_id else None
        state = {"fixed": {}, "custom": [], "form": None, **nav}
        threat_profile_card = with_nav_bar_v2(build_org_threats_card(state, profile, team_id=slack_team_id), "org_threats")

        # Launch Test hands off INTO Command Center -- it does not turn
        # this Threats Center channel into a copy of Command Center.
        # Previously this replaced the Threats Center message in place
        # with the full nav-bar'd card, which dragged the entire
        # Welcome/Admins/Teams/.../Trigger flow into the wrong channel.
        from workspaces.models import Workspace

        workspace = Workspace.objects(team_id=slack_team_id).first() if slack_team_id else None
        command_center_channel_id = workspace.new_design_preview_channel_id if workspace else ""
        if command_center_channel_id and bot_token:
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": command_center_channel_id, "text": "Threat Profile", **threat_profile_card},
                timeout=10,
            )
        if response_url:
            link = f"<#{command_center_channel_id}>" if command_center_channel_id else "Command Center"
            _replace_message(
                response_url,
                {"blocks": message_blocks + [{"type": "context", "elements": [{"type": "mrkdwn", "text": f":white_check_mark: Sent to {link} -- continue there to pick Incident/Cause/Phase/Scenario and trigger."}]}]},
            )
        return

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

    if action_id.startswith("v2_threat_cause_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_cause"] = action.get("value", "")
        state["active_phase"] = None
        state["active_scenario"] = None
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_phase_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        _, plan_id, phase = action_id.split("__", 2)
        state["active_phase"] = phase
        state["active_scenario"] = None
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id.startswith("v2_threat_scenario_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        _, plan_id, phase, scenario = action_id.split("__", 3)
        state["active_phase"] = phase
        state["active_scenario"] = scenario
        _redraw_threats(response_url, state, slack_team_id)
        return

    # "TestMyPlan" on Threat Profile's Incident view -- hands off to Step
    # 6 · Configure Test (cards/test_plan_v2_data.py's
    # build_configure_test_card), which now picks Cause, Phase AND
    # Scenario (sir's call -- Cause moved off Threat Profile, onto this
    # screen, same place Phase/Scenario already lived).
    if action_id == "v2_threat_configure_test":
        from .test_plan_v2_data import build_configure_test_card

        data = json.loads(action.get("value", "{}"))
        card = build_configure_test_card(
            data.get("module", ""), data.get("threat_key", ""), data.get("incident_id", ""),
            "", "", "", data.get("breadcrumb", {}), team_id=slack_team_id,
        )
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))
        return

    if action_id.startswith(("v2_cfgtest_cause_tab__", "v2_cfgtest_phase_tab__", "v2_cfgtest_scenario_tab__")):
        from .test_plan_v2_data import build_configure_test_card

        data = json.loads(action.get("value", "{}"))
        card = build_configure_test_card(
            data.get("module", ""), data.get("threat_key", ""), data.get("incident_id", ""),
            data.get("cause", ""), data.get("phase", ""), data.get("scenario", ""),
            data.get("breadcrumb", {}), team_id=slack_team_id,
        )
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))

        # A real popup (sir's call), not text on the Step 6 screen --
        # opened alongside the redraw above, using this same click's
        # trigger_id (only valid for this one interaction).
        if action_id.startswith("v2_cfgtest_cause_tab__"):
            from .cause_awareness_modal_v2 import open_modal

            trigger_id = payload.get("trigger_id", "")
            cause_id = data.get("cause", "")
            if trigger_id and cause_id and bot_token:
                open_modal(trigger_id, cause_id, bot_token)
        return

    if action_id == "v2_threat_trigger":
        # Step 6 "Test plan" review screen removed (sir's call) -- Launch
        # test now goes straight to arming + Training mode, same as the
        # TestMyPlan tab's own v2_plan_arm_real already does.
        import datetime

        breadcrumb = json.loads(action.get("value", "{}"))
        plan_id, phase, scenario = breadcrumb["plan_id"], breadcrumb["phase"], breadcrumb["scenario"]
        persistence_v2.save_scenario_selection(
            slack_team_id, plan_id, scenario_id=scenario, phase=phase, armed=True, armed_at=datetime.datetime.utcnow()
        )
        from .trigger_v2_data import build_training_mode_card

        card = build_training_mode_card(plan_id, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id == "v2_plan_view_summary":
        payload_data = json.loads(action.get("value", "{}"))
        from .test_plan_v2_data import build_plan_summary_card

        card = build_plan_summary_card(
            payload_data["plan_id"], slack_team_id=slack_team_id, bot_token=bot_token,
            back_phase=payload_data.get("phase", ""), back_scenario=payload_data.get("scenario", ""),
            breadcrumb=payload_data.get("breadcrumb"),
        )
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))
        return

    if action_id == "v2_plan_summary_back":
        payload_data = json.loads(action.get("value", "{}"))
        card = build_real_test_plan_card(
            payload_data["plan_id"], payload_data["phase"], payload_data["scenario"],
            breadcrumb=payload_data.get("breadcrumb"), slack_team_id=slack_team_id, bot_token=bot_token,
        )
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))
        return

    if action_id == "v2_nav_jump__org_threats":
        state = persistence_v2.load_threats_state(slack_team_id)
        _redraw_threats(response_url, state, slack_team_id)
        return

    if action_id == "v2_nav_jump__trigger":
        from .models_v2 import ScenarioSelection
        from .trigger_v2_data import build_training_mode_card

        sel = (
            ScenarioSelection.objects(team_id=slack_team_id, armed=True).order_by("-armed_at").first()
            if slack_team_id
            else None
        )
        if sel:
            card = build_training_mode_card(sel.module, sel.scenario_id)
        else:
            card = {
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: Trigger", "emoji": True}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": "_Nothing armed yet -- launch a test from Threat Profile or TestMyPlan first._"}},
                ]
            }
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id == "v2_nav_jump__admins":
        _redraw_admins(response_url, bot_token, current_user_id, persistence_v2.load_admins_state(slack_team_id))
        return

    if action_id == "v2_admin_toggle_modules":
        state = read_admins_state(message_blocks)
        selected = [opt.get("value", "") for opt in action.get("selected_options", [])]
        state["selected_modules"] = selected
        persistence_v2.save_selected_modules(slack_team_id, selected)
        # Drop assignments for modules the org just turned off -- no point
        # keeping an admin set on a module they said doesn't apply.
        for mod_id in list(state["assigned"]):
            if mod_id in ("cyber", "privacy") and mod_id not in selected:
                state["assigned"].pop(mod_id, None)
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id == "v2_admin_take_all":
        state = read_admins_state(message_blocks)
        for mod in state.get("selected_modules") or ("cyber", "privacy"):
            state["assigned"][mod] = current_user_id
        state["assigned"]["plans_bia"] = current_user_id
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
        if mod_id == "plans_bia":
            # Unlike the other modules' plain "you're admin" line, this
            # is a real job card with next steps -- worth sending even
            # when you assign it to yourself, not just when delegating
            # to someone else (confirmed live: self-assigning showed no
            # card at all before this).
            admin_notify_v2.send_admin_assigned_dm(slack_team_id, mod_id, current_user_id, bot_token)
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

    # "Continue" -- advances to the BIA/BCP upload step. A plan already
    # on file means they already answered "Yes" by uploading it -- skip
    # straight to the status screen instead of asking again.
    if action_id in ("v2_admins_done", "v2_nav_jump__bia_upload"):
        from .bia_upload_v2_data import build_bia_question_card, _latest_plan

        if slack_team_id and _latest_plan(slack_team_id) is not None:
            _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts)
        else:
            # Save the location here too (not just once a plan exists) so
            # a draft generated from the "No BCP" branch, which starts
            # from this exact screen, can still auto-refresh when ready.
            _replace_message(response_url, with_nav_bar_v2(build_bia_question_card(), "bia_upload"))
            if slack_team_id and top_channel_id and top_message_ts:
                persistence_v2.save_bia_upload_card_location(slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_bia_have_doc_yes":
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_bia_have_doc_no":
        from .bia_upload_v2_data import build_grc_department_card

        _replace_message(response_url, with_nav_bar_v2(build_grc_department_card(), "bia_upload"))
        return

    if action_id == "v2_bia_generate_draft":
        import datetime
        import threading

        from .bia_upload_v2_data import build_draft_requested_card
        from .models_v2 import DraftBiaRequest, OrgProfile

        profile = OrgProfile.objects(team_id=slack_team_id).first() if slack_team_id else None
        if slack_team_id:
            DraftBiaRequest.objects(team_id=slack_team_id).update_one(
                set__org_name=profile.org_name if profile else "",
                set__website_url=profile.website_url if profile else "",
                set__status="requested",
                set__error_message="",
                set__requested_at=datetime.datetime.utcnow(),
                upsert=True,
            )
            # Real research (web search, DNS, breach lookups) takes a
            # few minutes -- runs in the background, same pattern as a
            # DM upload, with a live push to this card when it's done.
            from plans.draft_generation import run_draft_generation_then_refresh

            threading.Thread(
                target=run_draft_generation_then_refresh, args=(slack_team_id, bot_token), daemon=True
            ).start()
        _replace_message(response_url, with_nav_bar_v2(build_draft_requested_card(slack_team_id), "bia_upload"))
        return

    if action_id == "v2_draft_review_open":
        from .bia_upload_v2_data import _latest_plan
        from .draft_confirmation_modal_v2 import open_modal

        trigger_id = payload.get("trigger_id", "")
        plan = _latest_plan(slack_team_id) if slack_team_id else None
        if trigger_id and plan and bot_token:
            open_modal(trigger_id, plan, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_bia_edit_rtos":
        from .bia_upload_v2_data import _latest_plan
        from .edit_rtos_modal_v2 import open_modal

        trigger_id = payload.get("trigger_id", "")
        plan = _latest_plan(slack_team_id) if slack_team_id else None
        if trigger_id and plan and bot_token:
            open_modal(trigger_id, plan, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_bia_refresh":
        from .bia_upload_v2_data import _latest_plan, build_draft_failed_card, build_draft_requested_card
        from .models_v2 import DraftBiaRequest

        draft_request = DraftBiaRequest.objects(team_id=slack_team_id).first() if slack_team_id else None
        no_plan_yet = not slack_team_id or _latest_plan(slack_team_id) is None
        if draft_request and no_plan_yet and draft_request.status == "failed":
            _replace_message(response_url, with_nav_bar_v2(build_draft_failed_card(slack_team_id), "bia_upload"))
            return
        if draft_request and no_plan_yet and draft_request.status == "requested":
            _replace_message(response_url, with_nav_bar_v2(build_draft_requested_card(slack_team_id), "bia_upload"))
            return
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts)
        return

    # "Make changes" -- loops back to the upload step, same shape as the
    # BIA/BCP-available No-branch and the org-details approval No-branch
    # elsewhere in this flow (sir's flowchart: "No -- again change and show").
    if action_id == "v2_ai_changes":
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_ai_approve":
        from plans.models import Plan

        plan = Plan.objects(slack_team_id=slack_team_id, is_latest=True).order_by("-created_at").first() if slack_team_id else None
        if plan is not None and plan.resilience_map_status != "approved":
            plan.resilience_map_status = "approved"
            plan.save()
        # Nav order is Upload & Analysis -> Teams -> Threat Profile, so
        # Approve continues to Teams next, not straight to Threat Profile.
        _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id), slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_nav_jump__teams":
        _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id), slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_team_priority_tab__"):
        state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        _, team_id, priority = action_id.split("__", 2)
        state["expanded_team"] = team_id
        state["active_priority"] = priority
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    # The real Welcome -> Role -> Acknowledge DM flow (role_welcome_v2.py,
    # built from userflow/assignmentcard.html) -- clicked by the assigned
    # PERSON in their own DM, not an admin in the command-center channel,
    # so these update that DM message directly via channel/ts rather than
    # the usual response_url.
    if action_id in ("v2_role_view", "v2_role_acknowledge", "v2_role_ack_confirm", "v2_role_decline"):
        from . import role_welcome_v2
        from .models_v2 import Team, TeamMember
        from .team_catalog_v2 import find_team

        dm_channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        value = action.get("value", "")
        if not (dm_channel_id and message_ts and bot_token and value):
            return

        catalog_team_id, role, is_backup = role_welcome_v2.parse_value(value)
        team_info = find_team(catalog_team_id)
        team_name = team_info["name"] if team_info else catalog_team_id
        team_doc = Team.objects(team_id=slack_team_id, slug=catalog_team_id).first()
        member = TeamMember.objects(team=team_doc, role=role).first() if team_doc else None

        if action_id == "v2_role_view":
            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            primary_name = by_code.get(member.primary_slack_user_ids[0], {}).get("n", "") if member and member.primary_slack_user_ids else ""
            backup_name = by_code.get(member.backup_slack_user_ids[0], {}).get("n", "") if member and member.backup_slack_user_ids else ""
            responsibility = member.mapped_responsibilities[0] if member and member.mapped_responsibilities else None
            card = role_welcome_v2.build_role_card(catalog_team_id, team_name, role, primary_name, backup_name, is_backup, responsibility, value)

        elif action_id == "v2_role_acknowledge":
            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            recipient_name = by_code.get(current_user_id, {}).get("n", "there")
            card = role_welcome_v2.build_ack_card(recipient_name, team_name, role, value)

        elif action_id == "v2_role_decline":
            import datetime

            now = datetime.datetime.utcnow()
            backup_notified = False
            if member:
                member.declined_by[current_user_id] = now
                member.save()

                # Only activate a backup when the PRIMARY declines -- a
                # backup declining has nobody further to fall back to.
                backup_ids = []
                if not is_backup:
                    backup_ids = [uid for uid in member.backup_slack_user_ids if uid != current_user_id]
                    if backup_ids:
                        backup_notified = role_welcome_v2.send_backup_activation_dm(backup_ids[0], catalog_team_id, team_name, role, bot_token)

                # Nobody left to cover this role -- either the backup
                # declined, or the primary declined with no backup on
                # file. Alert the People & Roles owner instead of letting
                # the gap go unnoticed.
                if not backup_notified:
                    role_welcome_v2.notify_module_owner_no_coverage(slack_team_id, team_name, role, current_user_id, bot_token)
            card = role_welcome_v2.build_decline_done_card(team_name, role, backup_notified)

        else:  # v2_role_ack_confirm
            import datetime

            now = datetime.datetime.utcnow()
            if member:
                member.acknowledged_by[current_user_id] = now
                member.save()
            card = role_welcome_v2.build_ack_done_card(now.strftime("%d %b %Y, %H:%M UTC"))

            # Push the acknowledgment straight to the admin's open
            # Configure Teams card in real time -- sir's call: status
            # shouldn't need the admin to re-open/refresh to see it.
            location = persistence_v2.load_teams_card_location(slack_team_id)
            if location.get("channel_id") and location.get("message_ts"):
                people = get_workspace_people(bot_token)
                teams_state = persistence_v2.load_teams_state(slack_team_id)
                fresh_card = with_nav_bar_v2(build_teams_card(teams_state, people, slack_team_id=slack_team_id), "teams")
                requests.post(
                    "https://slack.com/api/chat.update",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    json={"channel": location["channel_id"], "ts": location["message_ts"], **fresh_card},
                    timeout=10,
                )

        requests.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": dm_channel_id, "ts": message_ts, **card},
            timeout=10,
        )
        return

    if action_id == "v2_team_role_remove":
        value = action.get("value", "")
        team_id, _, role = value.partition("|")
        if team_id and role:
            saved = persistence_v2.load_teams_state(slack_team_id)
            teams, resp = saved["teams"], saved["resp"]
            teams[team_id] = [m for m in teams.get(team_id, []) if m["role"] != role]
            resp[team_id] = [r for r in resp.get(team_id, []) if r.get("who") != role]
            persistence_v2.save_teams_state(slack_team_id, teams, resp)

        state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        state["expanded_team"] = team_id
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id in ("v2_team_role_primary_select", "v2_team_role_backup_select"):
        block_id = action.get("block_id", "")
        try:
            _, team_id, role = block_id.split("|", 2)
        except ValueError:
            return
        selected = action.get("selected_option", {}).get("value", "")

        # Same reasoning as every other inline edit on this card -- the
        # visible message only ever shows ONE team's roles at a time, so
        # saving straight from the message would wipe every other team.
        saved = persistence_v2.load_teams_state(slack_team_id)
        teams, resp = saved["teams"], saved["resp"]
        teams.setdefault(team_id, [])
        member = next((m for m in teams[team_id] if m["role"] == role), None)
        if member is None:
            member = {"role": role, "primary": [], "backup": []}
            teams[team_id].append(member)

        if action_id == "v2_team_role_primary_select":
            member["primary"] = [selected] if selected and selected != "__none__" else []
            # A person just made primary can't also still be their own backup.
            member["backup"] = [c for c in member["backup"] if c != selected]
        else:
            member["backup"] = [selected] if selected and selected != "__none__" else []

        from .team_catalog_v2 import default_responsibility_for, find_team

        default_resp = default_responsibility_for(team_id, role) or teams_v2_data.ROLE_DEFAULT_RESP.get(role)
        if default_resp:
            resp.setdefault(team_id, [])
            resp[team_id] = [r for r in resp[team_id] if r.get("who") != role]
            resp[team_id].append({"who": role, **default_resp})

        persistence_v2.save_teams_state(slack_team_id, teams, resp)

        # Only DM the person whose field this click just set -- not both
        # primary AND backup every time either one changes. Previously
        # this fired send_team_assignment_dm (which notifies primary AND
        # backup) on every single select, so picking primary then backup
        # for the same role sent the primary a duplicate Welcome DM.
        if selected and selected != "__none__":
            from .team_assignment_notify_v2 import send_team_assignment_dm

            team_info = find_team(team_id)
            team_name = team_info["name"] if team_info else team_id
            people = get_workspace_people(bot_token)
            by_code = {p["i"]: p for p in people}
            if action_id == "v2_team_role_primary_select":
                send_team_assignment_dm(
                    slack_team_id, team_name, role, selected, "", default_resp, by_code, bot_token,
                    catalog_team_id=team_id,
                )
            else:
                send_team_assignment_dm(
                    slack_team_id, team_name, role, "", selected, default_resp, by_code, bot_token,
                    catalog_team_id=team_id,
                )

        state = read_teams_state(message_blocks)
        state["teams"], state["resp"] = teams, resp
        state["expanded_team"] = team_id
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_team_add_open":
        state = read_teams_state(message_blocks)
        state["add"] = {"team_id": action.get("value", ""), "role": None, "primary": [], "backup": []}
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_team_bulk_assign_open":
        from . import bulk_assign_modal_v2

        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        if trigger_id and channel_id and bot_token:
            people = get_workspace_people(bot_token)
            saved = persistence_v2.load_teams_state(slack_team_id)
            bulk_assign_modal_v2.open_modal(trigger_id, channel_id, message_ts, people, saved["teams"], bot_token)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_team_member_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        add = state.get("add") or {}
        add["primary"] = [selected] if selected and selected != "__none__" else []
        # A person just made the member can't also still be their own backup.
        add["backup"] = [c for c in add.get("backup", []) if c != selected]
        state["add"] = add
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_team_backup_select":
        selected = action.get("selected_option", {}).get("value", "")
        state = read_teams_state(message_blocks)
        add = state.get("add") or {}
        add["backup"] = [selected] if selected and selected != "__none__" else []
        state["add"] = add
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
                catalog_team_id=team_id,
            )
        # If required fields are missing, leave the form open as-is
        # rather than silently discarding what's already picked.
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_team_copy_open":
        from . import team_copy_modal_v2

        source_team_id = action.get("value", "")
        trigger_id = payload.get("trigger_id", "")
        channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        if trigger_id and channel_id and bot_token and source_team_id:
            team_copy_modal_v2.open_modal(trigger_id, source_team_id, channel_id, message_ts, bot_token, slack_team_id=slack_team_id)
        return

    if action_id == "v2_team_add_cancel":
        state = read_teams_state(message_blocks)
        state["add"] = None
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_resp_who_toggle__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        map_state["who"] = action.get("value", "")
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_resp_action_pick__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        # Picking a new action type invalidates whatever exact-action
        # was chosen -- that list is specific to the previous type.
        map_state["action"] = action.get("value", "")
        map_state["detail"] = None
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_resp_phase_pick__"):
        state = read_teams_state(message_blocks)
        map_state = state.get("map") or {}
        map_state["phase"] = action.get("value", "")
        state["map"] = map_state
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_resp_map_done":
        state = read_teams_state(message_blocks)
        state["map"] = None
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
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
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    # Select a team from the team-tab row (each team's button needs its
    # own unique action_id -- Slack rejects a message where multiple
    # elements share one action_id, which is why these used to all break
    # at once with "invalid_blocks").
    if action_id.startswith("v2_team_expand_toggle__"):
        # Same reasoning as the tier switch above -- load real team data
        # from the DB so opening/closing a team never loses another team's
        # already-saved members.
        message_state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state = {**message_state, "teams": saved["teams"], "resp": saved["resp"]}
        value = action.get("value", "")
        state["expanded_team"] = None if value == "__none__" else (value or None)
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    # "Jump to a team…" -- finds that team's own tier and switches
    # straight to it, instead of having to click through tier tabs one at
    # a time to locate one specific team out of 35.
    if action_id == "v2_team_jump_select":
        from .team_catalog_v2 import find_team

        target_id = action.get("selected_option", {}).get("value", "")
        target_team = find_team(target_id)
        if target_team:
            message_state = read_teams_state(message_blocks)
            saved = persistence_v2.load_teams_state(slack_team_id)
            state = {**message_state, "teams": saved["teams"], "resp": saved["resp"]}
            state["active_tier"] = target_team["tier"]
            state["expanded_team"] = target_id
            _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id in ("v2_teams_continue", "v2_teams_done"):
        # v2_teams_continue replaces the old v2_teams_done button (sir's
        # call -- old one stopped responding in Slack, fresh action_id to
        # rule out a stale/cached button). Goes straight to Threat Profile,
        # matching the nav order (Teams -> Threat Profile -> TestMyPlan).
        # Calls _redraw_threats directly (not a reassign-and-fallthrough)
        # because the "v2_nav_jump__org_threats" check this used to fall
        # into sits EARLIER in this file (line ~550) than this handler --
        # a sequential if-chain, not a loop, so that reassignment trick
        # never actually re-triggered anything; it just silently fell
        # through to the end of the function. This was the real root
        # cause of the button looking like it "did nothing."
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

    if action_id in ("v2_threat_scenario_generate", "v2_threat_scenario_review"):
        from .scenario_v2_data import _breadcrumb, build_generating_card, build_scenario_failed_card, build_scenario_review_card
        from .threat_map_v2_data import _find_incident, _find_threat
        from .models_v2 import GeneratedScenario
        from plans.scenario_generator import generate_scenario

        if action_id == "v2_threat_scenario_review":
            doc = GeneratedScenario.objects(id=action.get("value", "")).first()
            if not doc:
                return
            breadcrumb = _breadcrumb(doc.module, doc.threat_id, doc.incident_id, doc.cause_id)
            if response_url:
                _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb), "org_threats"))
            return

        module, threat_id, incident_id, cause_id = action.get("value", "").split("|", 3)
        breadcrumb = _breadcrumb(module, threat_id, incident_id, cause_id)

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_generating_card(breadcrumb), "org_threats"))

        threat = _find_threat(module, threat_id)
        incident = _find_incident(module, threat_id, incident_id)
        cause = next((c for c in (incident or {}).get("causes", []) if c["id"] == cause_id), None) if incident else None
        threat_label = threat["label"] if threat else threat_id
        incident_name = incident["name"] if incident else incident_id
        cause_name = cause["name"] if cause else cause_id

        result = generate_scenario(slack_team_id, threat_label, incident_name, cause_name, ["Identification", "Containment"])
        if not result or not result.get("injects"):
            if response_url:
                _replace_message(
                    response_url,
                    with_nav_bar_v2(
                        build_scenario_failed_card(
                            breadcrumb,
                            "Couldn't write a scenario -- make sure a real plan is uploaded and roles are assigned for this workspace, then try again.",
                        ),
                        "org_threats",
                    ),
                )
            return

        doc = GeneratedScenario(
            team_id=slack_team_id, module=module, threat_id=threat_id, incident_id=incident_id, cause_id=cause_id,
            threat_label=threat_label, incident_name=incident_name, cause_name=cause_name,
            phases=["Identification", "Containment"],
            injects=result["injects"], consequence_injects=result.get("consequence_injects", []),
        )
        doc.save()

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb), "org_threats"))
        return

    if action_id in ("v2_ai_training_yes", "v2_ai_training_no"):
        from . import ai_drill_v2
        from .models_v2 import GeneratedScenario

        scenario = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not scenario or not bot_token:
            return
        training_mode = action_id == "v2_ai_training_yes"
        if training_mode:
            ai_drill_v2.send_pre_notification(scenario, bot_token)
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_timing_picker_card(scenario, training_mode), "org_threats"))
        return

    if action_id == "v2_ai_trigger_now":
        from . import ai_drill_v2
        from .models_v2 import GeneratedScenario

        scenario_id, _, training_flag = action.get("value", "").partition("|")
        scenario = GeneratedScenario.objects(id=scenario_id).first()
        if not scenario or not bot_token:
            return
        run = ai_drill_v2.start_run(
            scenario, "now", current_user_id, bot_token, origin_channel_id=top_channel_id, training_mode=training_flag == "1",
        )
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_run_status_card(run, scenario), "org_threats"))
        return

    if action_id == "v2_ai_trigger_surprise":
        import datetime
        import random

        from . import ai_drill_v2
        from .models_v2 import GeneratedScenario

        scenario_id, _, training_flag = action.get("value", "").partition("|")
        scenario = GeneratedScenario.objects(id=scenario_id).first()
        if not scenario or not bot_token:
            return
        # Simple surprise window: a random time 1-24 hours from now --
        # keeps the real "nobody knows exactly when" effect without
        # needing a separate window-picker modal.
        scheduled_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=random.randint(60, 24 * 60))
        run = ai_drill_v2.start_run(
            scenario, "surprise", current_user_id, bot_token, scheduled_at=scheduled_at,
            origin_channel_id=top_channel_id, training_mode=training_flag == "1",
        )
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_run_status_card(run, scenario), "org_threats"))
        return

    if action_id == "v2_ai_trigger_schedule_open":
        from .ai_trigger_schedule_modal_v2 import open_modal

        trigger_id = payload.get("trigger_id", "")
        scenario_id, _, training_flag = action.get("value", "").partition("|")
        if trigger_id and bot_token:
            open_modal(trigger_id, scenario_id, top_channel_id, bot_token, training_mode=training_flag == "1")
        return

    if action_id.startswith("v2_ai_decision_choose__"):
        from . import ai_drill_v2

        ai_drill_v2.handle_decision(payload, bot_token)
        return

    if action_id == "v2_scenario_generate":
        from .scenario_v2_data import _breadcrumb, build_generating_card, build_scenario_failed_card, build_scenario_review_card
        from .threat_map_v2_data import _find_incident, _find_threat
        from .models_v2 import GeneratedScenario
        from plans.scenario_generator import generate_scenario

        module, threat_id, incident_id, cause_id = action.get("value", "").split(":", 3)
        breadcrumb = _breadcrumb(module, threat_id, incident_id, cause_id)

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_generating_card(breadcrumb), "threat_map"))

        threat = _find_threat(module, threat_id)
        incident = _find_incident(module, threat_id, incident_id)
        cause = next((c for c in (incident or {}).get("causes", []) if c["id"] == cause_id), None) if incident else None
        threat_label = threat["label"] if threat else threat_id
        incident_name = incident["name"] if incident else incident_id
        cause_name = cause["name"] if cause else cause_id

        result = generate_scenario(slack_team_id, threat_label, incident_name, cause_name, ["Identification", "Containment"])
        if not result or not result.get("injects"):
            if response_url:
                _replace_message(
                    response_url,
                    with_nav_bar_v2(
                        build_scenario_failed_card(
                            breadcrumb,
                            "Couldn't write a scenario -- make sure a real plan is uploaded and roles are assigned for this workspace, then try again.",
                        ),
                        "threat_map",
                    ),
                )
            return

        doc = GeneratedScenario(
            team_id=slack_team_id, module=module, threat_id=threat_id, incident_id=incident_id, cause_id=cause_id,
            threat_label=threat_label, incident_name=incident_name, cause_name=cause_name,
            phases=["Identification", "Containment"],
            injects=result["injects"], consequence_injects=result.get("consequence_injects", []),
        )
        doc.save()

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb), "threat_map"))
        return

    if action_id in ("v2_scenario_approve", "v2_scenario_regenerate"):
        from .scenario_v2_data import _breadcrumb, build_generating_card, build_scenario_failed_card, build_scenario_review_card
        from .models_v2 import GeneratedScenario
        from plans.scenario_generator import generate_scenario

        doc = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not doc:
            return
        breadcrumb = f"{doc.threat_label}  ›  {doc.incident_name}  ›  {doc.cause_name}"

        if action_id == "v2_scenario_approve":
            import datetime

            doc.status = "approved"
            doc.approved_by_slack_user_id = current_user_id
            doc.approved_at = datetime.datetime.utcnow()
            doc.save()
            if response_url:
                _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb), "org_threats"))
            return

        # v2_scenario_regenerate -- discard this proposal and write a new one
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_generating_card(breadcrumb), "org_threats"))
        result = generate_scenario(doc.team_id, doc.threat_label, doc.incident_name, doc.cause_name, doc.phases)
        if not result or not result.get("injects"):
            doc.delete()
            if response_url:
                _replace_message(response_url, with_nav_bar_v2(build_scenario_failed_card(breadcrumb, "The regeneration attempt failed -- try again."), "org_threats"))
            return
        doc.injects = result["injects"]
        doc.consequence_injects = result.get("consequence_injects", [])
        doc.status = "proposed"
        doc.approved_by_slack_user_id = None
        doc.approved_at = None
        doc.save()
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb), "org_threats"))
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
        from .trigger_v2_data import build_training_mode_card

        card = build_training_mode_card(module, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id == "v2_plan_arm_real":
        plan_id, phase, scenario = action.get("value", "").split(":", 2)
        import datetime

        persistence_v2.save_scenario_selection(
            slack_team_id, plan_id, scenario_id=scenario, phase=phase, armed=True, armed_at=datetime.datetime.utcnow()
        )
        from .trigger_v2_data import build_training_mode_card

        card = build_training_mode_card(plan_id, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id in ("v2_trigger_training_yes", "v2_trigger_training_no"):
        from .trigger_v2_data import build_trigger_card, send_pre_notification

        module, _, scenario = action.get("value", "").partition(":")
        if action_id == "v2_trigger_training_yes" and slack_team_id and bot_token:
            send_pre_notification(slack_team_id, module, scenario, bot_token)
        card = build_trigger_card(module, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id.startswith("v2_trigger_pick__"):
        module, scenario, trigger_key = action.get("value", "").split(":", 2)
        slack_team_id = payload.get("team", {}).get("id", "")
        bot_token = get_bot_token(slack_team_id)

        # "Schedule" previously fired the drill immediately, identically
        # to "Trigger now", despite claiming "pick a window" -- it now
        # actually asks for a date/time via a modal instead, and doesn't
        # create or fire anything until that's submitted (see
        # trigger_schedule_modal_v2.handle_submission).
        if trigger_key == "sched":
            from . import trigger_schedule_modal_v2

            trigger_id = payload.get("trigger_id", "")
            channel_id = payload.get("channel", {}).get("id", "")
            message_ts = payload.get("message", {}).get("ts", "")
            if trigger_id and channel_id and bot_token:
                trigger_schedule_modal_v2.open_modal(trigger_id, module, scenario, channel_id, message_ts, bot_token)
            return

        from exercises.models import Exercise
        from workspaces.models import Workspace

        # If "module" is really a real plan_id (reached via the
        # Launch-test path), carry through which Phase was armed -- the
        # live inject chain starts there and stays within that phase,
        # instead of always running the whole plan from the start.
        armed_selection = persistence_v2.load_scenario_selection(slack_team_id, module)
        inject_phase = armed_selection.get("phase") or ""

        exercise = Exercise(
            scenario_name=scenario,
            module=module,
            trigger_type=trigger_key,
            inject_phase=inject_phase,
            started_by_slack_user_id=current_user_id,
            slack_team_id=slack_team_id,
        )

        workspace = Workspace.objects(team_id=slack_team_id).first()
        # The real alarm goes into the real war-room/privacy-bridge
        # channel, not the admin's own command-center channel.
        target_channel_id = ""
        if workspace:
            target_channel_id = (
                workspace.privacy_bridge_channel_id if module == "Privacy" else workspace.ir_war_room_channel_id
            ) or ""
        exercise.slack_channel_id = target_channel_id

        if trigger_key == "surprise":
            # Same bug "Schedule" had -- this used to fire immediately
            # despite claiming "within the next 7 days". Reuses the exact
            # same scheduled_at + background-fire mechanism "Schedule"
            # uses, just with a random time instead of an admin-picked
            # one -- and the exact time is never shown back, since
            # revealing it would defeat the point of a surprise drill.
            import datetime
            import random

            exercise.status = "scheduled"
            exercise.scheduled_at = datetime.datetime.utcnow() + datetime.timedelta(
                seconds=random.randint(60, 7 * 24 * 60 * 60)
            )
            exercise.save()

            card = build_trigger_card(module, scenario, "surprise")
            card["blocks"].insert(
                1,
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": ":game_die: *Surprise window armed* — it'll fire at a random time within the next 7 days. No further action needed."}
                    ],
                },
            )
            _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
            return

        # "now" -- fire immediately.
        from exercises.drill import fire_exercise

        exercise.save()
        fire_exercise(exercise, bot_token)

        card = build_live_card(module, scenario, trigger_key, exercise=exercise)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    if action_id == "v2_trigger_cancel_scheduled":
        module, _, scenario = action.get("value", "").partition(":")
        slack_team_id = payload.get("team", {}).get("id", "")

        from exercises.models import Exercise

        Exercise.objects(
            status="scheduled", slack_team_id=slack_team_id, module=module, scenario_name=scenario
        ).delete()

        card = build_trigger_card(module, scenario)
        _replace_message(response_url, with_nav_bar_v2(card, "trigger"))
        return

    # Real inline select-then-Submit for a drill decision: clicking an
    # A/B/C/D button just marks it selected (highlighted), clicking
    # Submit reads whichever one is currently highlighted and finalises
    # it -- same two-step interaction as the mockup, no modal needed.
    if action_id.startswith("v2_decision_select__"):
        option = action_id.removeprefix("v2_decision_select__")
        response_id = action.get("value", "")
        dm_channel_id = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        if response_id and option:
            from .inject_drill_v2 import handle_decision_select

            handle_decision_select(response_id, option, dm_channel_id, message_ts, bot_token)
        return

    if action_id == "v2_decision_submit":
        response_id = action.get("value", "")
        if response_id:
            from .inject_drill_v2 import handle_decision_submit

            handle_decision_submit(response_id, message_blocks, bot_token)
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

    if action_id == "v2_nav_jump__test_plan":
        # Clicking the TestMyPlan tab directly (not via the Threat Profile
        # Trigger button) had no handler at all -- fell through to the
        # generic no-op below and did nothing. Reconstruct the real plan
        # card from whatever was last picked on Threat Profile instead.
        from .plan_catalog_v2 import find_plan_id_for_taxonomy
        from .threat_map_v2_data import _find_threat
        from .threats_v2_data import THREATS

        nav = persistence_v2.load_threat_profile_nav(slack_team_id) if slack_team_id else {}
        active_module = nav.get("active_module")
        raw_key = nav.get("active_threat")
        active_incident = nav.get("active_incident")
        active_cause = nav.get("active_cause")
        active_phase = nav.get("active_phase")
        active_scenario = nav.get("active_scenario")
        active_crit = nav.get("active_crit")

        plan_id = None
        if active_module and raw_key and active_incident and active_cause:
            plan_id = find_plan_id_for_taxonomy(active_module, raw_key, active_incident, active_cause)

        if plan_id and active_phase and active_scenario:
            # Same breadcrumb trail the Trigger button passes -- reconstructed
            # here from the real taxonomy so it shows the same way whether you
            # got here by clicking Trigger or jumping straight to this tab.
            threat_label = next((t["label"] for t in THREATS if t["key"] == raw_key), raw_key)
            taxonomy_threat = _find_threat(active_module, raw_key)
            incident_name, cause_name = active_incident, active_cause
            if taxonomy_threat:
                incident = next((inc for inc in taxonomy_threat["incidents"] if inc["id"] == active_incident), None)
                if incident:
                    incident_name = incident["name"]
                    cause = next((c for c in incident["causes"] if c["id"] == active_cause), None)
                    if cause:
                        cause_name = cause["name"]
            breadcrumb = {
                "module": active_module, "crit": active_crit, "threat": threat_label,
                "incident": incident_name, "cause": cause_name, "phase": active_phase, "scenario": active_scenario,
            }
            card = build_real_test_plan_card(
                plan_id, active_phase, active_scenario, breadcrumb=breadcrumb, slack_team_id=slack_team_id, bot_token=bot_token,
            )
        elif plan_id:
            # A real Threat -> Incident -> Cause is picked, just not
            # Phase/Scenario yet -- show the Configure Test picker
            # instead of a dead-end message.
            from .test_plan_v2_data import build_configure_test_card

            card = build_configure_test_card(
                active_module, raw_key, active_incident, active_cause,
                active_phase or "", active_scenario or "", _breadcrumb_from_nav(nav), team_id=slack_team_id,
            )
        else:
            card = {
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Configure test", "emoji": True}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": "_Pick a Threat → Incident on Threat Profile first, then TestMyPlan to see it here._"}},
                ]
            }
        _replace_message(response_url, with_nav_bar_v2(card, "test_plan"))
        return

    if action_id.startswith("v2_nav_jump__"):
        # Nav tabs for steps not built yet -- nothing to show, leave the
        # current card as-is rather than erroring or going blank.
        return
