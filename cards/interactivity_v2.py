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
from . import team_role_modal_v2
from .admins_v2_data import build_admins_card
from .admins_v2_data import read_current_state as read_admins_state
from .bia_upload_v2_data import build_bia_upload_card
from .nav_v2 import with_nav_bar_v2
from .slack_members_v2 import get_workspace_people
from . import teams_v2_data
from .teams_v2_data import ADD_CUSTOM_ROLE_VALUE, build_teams_card
from .teams_v2_data import read_current_state as read_teams_state
from .threats_v2_data import build_org_threats_card, read_current_state
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


def _replace_message(response_url: str, card: dict, bot_token: str = "", channel_id: str = "", message_ts: str = "") -> None:
    # Slack only accepts 5 response_url posts per 30 minutes, total,
    # across every click on that one message. Threat Mapping's own
    # drill-down (Module -> Severity tab -> Threat tab -> Incident tab)
    # already burns through several of those before "Build scenario" is
    # even reached -- confirmed live: clicking Build scenario after
    # drilling down silently did nothing, no error shown anywhere,
    # because the response_url had already hit its limit. chat.update
    # (channel + the message's own ts) has no such limit, so it's used
    # whenever the caller has those on hand; response_url stays as the
    # fallback for callers that don't.
    if bot_token and channel_id and message_ts:
        resp = requests.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel_id, "ts": message_ts, **card},
            timeout=10,
        )
        body = resp.json() if resp.content else {}
        if body.get("ok") is not True:
            logger.warning("chat.update was not accepted (status=%s): %s", resp.status_code, str(body)[:500])
        return
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


def _redraw_threats(response_url: str, state: dict, slack_team_id: str = "", bot_token: str = "", channel_id: str = "", message_ts: str = "") -> None:
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

    _replace_message(response_url, with_nav_bar_v2(card, "org_threats"), bot_token, channel_id, message_ts)


def _breadcrumb_from_nav(nav: dict, team_id: str = "") -> dict:
    """Turns the saved threat_profile_nav ids back into display labels --
    same lookup v2_nav_jump__test_plan already does, factored out so the
    Configure Test phase/scenario tab clicks (which only have the nav,
    not the full Threat Profile message) can show the same breadcrumb.

    Confirmed live: this used to only check the OLD fixed taxonomy
    (threats_v2_data.THREATS / threat_map_v2_data._find_threat) -- for
    any AI-generated threat (not in that fixed list, which is almost
    every real org threat now) it silently fell back to the raw snake_
    case keys/ids instead of the real names, e.g. "client_data_integrity_
    attack" / "skewed_metrics" instead of "Client Data Integrity
    Tampering" / "Inaccurate BI Reporting". Looked "random" because it
    only broke depending on which taxonomy that particular threat came
    from, not on anything the admin did differently. resolve_names
    already checks BOTH taxonomies correctly (used by Configure Test's
    own cause generation) -- reused here instead of duplicating a second,
    incomplete lookup."""
    from .threat_profile_review_v2 import resolve_names

    active_module = nav.get("active_module")
    raw_key = nav.get("active_threat")
    threat_label, incident_name, cause_name = raw_key, nav.get("active_incident"), nav.get("active_cause")
    if active_module and raw_key:
        threat_label, incident_name, cause_name = resolve_names(
            team_id, active_module, raw_key, nav.get("active_incident") or "", nav.get("active_cause") or "",
        )
    return {
        "module": active_module, "crit": nav.get("active_crit"), "threat": threat_label,
        "incident": incident_name, "cause": cause_name,
    }


def _redraw_admins(response_url: str, bot_token: str, current_user_id: str, state: dict) -> None:
    people = get_workspace_people(bot_token)
    _replace_message(response_url, with_nav_bar_v2(build_admins_card(state, people, current_user_id), "admins"))


def _redraw_bia_upload(response_url: str, slack_team_id: str, channel_id: str = "", message_ts: str = "", user_id: str = "", bot_token: str = "") -> None:
    _replace_message(
        response_url,
        with_nav_bar_v2(build_bia_upload_card(slack_team_id, user_id, bot_token), "bia_upload"),
        bot_token=bot_token,
        channel_id=channel_id,
        message_ts=message_ts,
    )
    if slack_team_id and channel_id and message_ts:
        persistence_v2.save_bia_upload_card_location(slack_team_id, channel_id, message_ts)


def _redraw_teams(response_url: str, bot_token: str, state: dict, slack_team_id: str = "", channel_id: str = "", message_ts: str = "") -> None:
    people = get_workspace_people(bot_token)
    _replace_message(
        response_url,
        with_nav_bar_v2(build_teams_card(state, people, slack_team_id=slack_team_id), "teams"),
        bot_token=bot_token,
        channel_id=channel_id,
        message_ts=message_ts,
    )
    if slack_team_id and channel_id and message_ts:
        persistence_v2.save_teams_card_location(slack_team_id, channel_id, message_ts)


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

    if action_id == "v2_orgsetup_continue":
        from . import threat_profile_review_v2

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id == "v2_nav_jump__threat_review":
        from . import threat_profile_review_v2

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id.startswith("v2_tpreview_module_tab__"):
        from . import threat_profile_review_v2

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=action.get("value", "")), "threat_review"))
        return

    if action_id == "v2_tpreview_page_noop":
        return

    if action_id == "v2_tpreview_page":
        from . import threat_profile_review_v2

        value = action.get("value", "")
        module, _, page_str = value.rpartition("|")
        try:
            page = int(page_str)
        except ValueError:
            page = 0
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=module, active_page=page), "threat_review"))
        return

    if action_id == "v2_tpreview_retry":
        from . import threat_profile_review_v2

        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id == "v2_tpreview_regenerate":
        from . import threat_profile_review_v2

        threat_profile_review_v2.regenerate_profile(slack_team_id)
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id == "v2_tpreview_approve":
        from . import threat_profile_review_v2
        from .bia_upload_v2_data import build_bia_question_card, _latest_plan

        threat_profile_review_v2.approve_profile(slack_team_id)
        if slack_team_id and _latest_plan(slack_team_id) is not None:
            _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        else:
            _replace_message(response_url, with_nav_bar_v2(build_bia_question_card(), "bia_upload"))
            if slack_team_id and top_channel_id and top_message_ts:
                persistence_v2.save_bia_upload_card_location(slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_tpreview_continue":
        # Same destination as Approve's own continue step, but for an
        # already-approved profile -- sir's call: without this, getting
        # back here (e.g. via the nav bar) left no way forward except
        # Edit again -> Approve, even though nothing needed re-approving.
        from .bia_upload_v2_data import build_bia_question_card, _latest_plan

        if slack_team_id and _latest_plan(slack_team_id) is not None:
            _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        else:
            _replace_message(response_url, with_nav_bar_v2(build_bia_question_card(), "bia_upload"))
            if slack_team_id and top_channel_id and top_message_ts:
                persistence_v2.save_bia_upload_card_location(slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_tpreview_reopen":
        from . import threat_profile_review_v2

        threat_profile_review_v2.reopen_profile(slack_team_id)
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id == "v2_tpreview_remove_select":
        from . import threat_profile_review_v2

        key = (action.get("selected_option") or {}).get("value", "")
        if key:
            threat_profile_review_v2.remove_threat(slack_team_id, key)
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id.startswith("v2_tpreview_remove__"):
        from . import threat_profile_review_v2

        key = action_id.removeprefix("v2_tpreview_remove__")
        threat_profile_review_v2.remove_threat(slack_team_id, key)
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"))
        return

    if action_id == "v2_tpreview_add":
        from . import threat_profile_review_v2

        trigger_id = payload.get("trigger_id", "")
        if trigger_id and bot_token:
            requests.post(
                "https://slack.com/api/views.open",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"trigger_id": trigger_id, "view": threat_profile_review_v2.build_add_modal_view(top_channel_id, top_message_ts)},
                timeout=10,
            )
        return

    if action_id == "v2_tpreview_edit":
        from . import threat_profile_review_v2

        trigger_id = payload.get("trigger_id", "")
        module = action.get("value", "")
        if trigger_id and bot_token:
            requests.post(
                "https://slack.com/api/views.open",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "trigger_id": trigger_id,
                    "view": threat_profile_review_v2.build_edit_modal_view(slack_team_id, module, top_channel_id, top_message_ts),
                },
                timeout=10,
            )
        return

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
        from .onboarding_v2 import build_admin_welcome_card

        card = build_admin_welcome_card(slack_team_id, current_user_id, bot_token)
        _replace_message(response_url, with_nav_bar_v2(card, "welcome"), bot_token, top_channel_id, top_message_ts)
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
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_module_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_module"] = action.get("value", "Cybersecurity")
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_crit_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_crit"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_name_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_threat"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_incident_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_incident"] = action.get("value", "")
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    # "+ Add a threat we missed" -- opens the inline form.
    if action_id == "v2_threat_add_open":
        state = read_current_state(message_blocks)
        state["form"] = {"module": None, "threat": None, "crit": None}
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_threat_add_module_select":
        state = read_current_state(message_blocks)
        new_module = action.get("selected_option", {}).get("value", "")
        # Changing the module resets the threat pick -- the previous
        # threat came from the OTHER module's catalog.
        state["form"] = {"module": new_module, "threat": None, "crit": (state.get("form") or {}).get("crit")}
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_threat_add_threat_select":
        state = read_current_state(message_blocks)
        value = action.get("selected_option", {}).get("value", "")
        form = state.get("form") or {}
        form["threat"] = None if value == "__none__" else value
        state["form"] = form
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_add_crit__"):
        state = read_current_state(message_blocks)
        form = state.get("form") or {}
        form["crit"] = action_id.removeprefix("v2_threat_add_crit__")
        state["form"] = form
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
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
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_threat_add_cancel":
        state = read_current_state(message_blocks)
        state["form"] = None
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_cause_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        state["active_cause"] = action.get("value", "")
        state["active_phase"] = None
        state["active_scenario"] = None
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_phase_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        _, plan_id, phase = action_id.split("__", 2)
        state["active_phase"] = phase
        state["active_scenario"] = None
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_threat_scenario_tab__"):
        state = read_current_state(message_blocks)
        saved = persistence_v2.load_threats_state(slack_team_id)
        state["fixed"], state["custom"] = saved["fixed"], saved["custom"]
        _, plan_id, phase, scenario = action_id.split("__", 3)
        state["active_phase"] = phase
        state["active_scenario"] = scenario
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_cfgtest_run_incident":
        # Incident-wide testing (sir's call): one button writes (or
        # reuses) every Cause's own scenario under this Incident, merges
        # them into a single combined drill, and shows it for review --
        # no more picking one Cause at a time.
        data = json.loads(action.get("value", "{}"))
        module, threat_key, incident_id = data.get("module", ""), data.get("threat_key", ""), data.get("incident_id", "")
        breadcrumb = data.get("breadcrumb", {})

        message_blocks = payload.get("message", {}).get("blocks", [])
        threats_state = read_current_state(message_blocks)
        threats_saved = persistence_v2.load_threats_state(slack_team_id) if slack_team_id else {"fixed": {}, "custom": []}
        threats_state["fixed"], threats_state["custom"] = threats_saved["fixed"], threats_saved["custom"]

        if response_url:
            # Instant feedback before the slow AI calls below even start
            # -- same reasoning as the old per-cause loading state, just
            # for every cause in this incident at once now. Redraws the
            # SAME Threat Mapping screen the admin is already looking at
            # (causes list, button, breadcrumb all still there) with just
            # a status note added -- no separate screen swap -- sir's call.
            loading_card = build_org_threats_card(threats_state, team_id=slack_team_id)
            loading_card["blocks"].append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":hourglass_flowing_sand: Writing the scenario for this incident -- this can take a minute or two."}],
            })
            _replace_message(response_url, with_nav_bar_v2(loading_card, "org_threats"), bot_token, top_channel_id, top_message_ts)

        from .incident_test_v2 import get_or_generate_incident_scenario, send_awareness_dms
        from .threat_map_v2_data import _find_threat
        from .threat_profile_review_v2 import ensure_threat_map

        taxonomy_threat = _find_threat(module, threat_key) if module and threat_key else None
        incidents = (taxonomy_threat or {}).get("incidents", [])
        if not incidents and slack_team_id and threat_key:
            incidents = ensure_threat_map(slack_team_id, threat_key)
        incident = next((i for i in incidents if i["id"] == incident_id), None)
        causes = incident["causes"] if incident else []

        if causes and slack_team_id and bot_token:
            # Instant (no AI call -- the what/why is already written and
            # cached) -- fires before the slow scenario generation below
            # so the team hears about this incident right away, not only
            # once the (10-30s+) AI write finishes.
            send_awareness_dms(slack_team_id, module, threat_key, incident_id, causes, bot_token)

        combined = get_or_generate_incident_scenario(slack_team_id, module, threat_key, incident_id, causes) if causes else None

        if combined == "missing_plan_or_roles":
            card = build_org_threats_card(threats_state, team_id=slack_team_id)
            card["blocks"].append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Couldn't write a scenario -- this team doesn't have a real plan (services) or roles set up yet. Add those first, then try again._"}],
            })
        elif combined:
            from .scenario_v2_data import build_scenario_review_card

            scenario_breadcrumb = "  ›  ".join(
                v for v in (breadcrumb.get("module"), breadcrumb.get("crit"), breadcrumb.get("threat"), breadcrumb.get("incident")) if v
            )
            card = build_scenario_review_card(combined, scenario_breadcrumb)
        else:
            card = build_org_threats_card(threats_state, team_id=slack_team_id)
            card["blocks"].append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Couldn't write a scenario for this incident -- this can happen when the AI provider is briefly overloaded. Try again._"}],
            })
        _replace_message(response_url, with_nav_bar_v2(card, "org_threats"), bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_cfgtest_view_scenario":
        # Jumps straight to an already-built scenario's review screen
        # instead of making the admin click "Build scenario" again just
        # to see the same thing (which does nothing new -- it's the same
        # combined lookup get_or_generate_incident_scenario already does).
        from .models_v2 import GeneratedScenario
        from .scenario_v2_data import build_scenario_review_card

        doc = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not doc or not response_url:
            return
        scenario_breadcrumb = "  ›  ".join(v for v in (doc.threat_label, doc.incident_name, doc.cause_name) if v)
        card = build_scenario_review_card(doc, scenario_breadcrumb)
        _replace_message(response_url, with_nav_bar_v2(card, "org_threats"), bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_nav_jump__org_threats":
        state = persistence_v2.load_threats_state(slack_team_id)
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_nav_jump__trigger":
        from .models_v2 import AIExerciseRun, GeneratedScenario, RUN_STATUS_RUNNING, RUN_STATUS_SCHEDULED

        # Confirmed live: coming back to this tab mid-drill (e.g. after
        # checking Teams & Roles) re-asked "Training mode?" for some
        # OTHER approved-but-unrun scenario instead of showing the
        # drill that's actually running -- the only way to reach the
        # Preparedness report was a response_url left over from before
        # navigating away. An active run always wins over anything else
        # here, since there's nothing else to meaningfully do on this
        # tab while one is in progress.
        active_run = (
            AIExerciseRun.objects(team_id=slack_team_id, status__in=[RUN_STATUS_RUNNING, RUN_STATUS_SCHEDULED])
            .order_by("-started_at")
            .first()
            if slack_team_id
            else None
        )

        # An approved AI scenario that hasn't been run yet asks "Training
        # mode?" here too, not just right after Approve, so coming back
        # to this tab later still finds it.
        approved_ai_scenario = None
        if slack_team_id and active_run is None:
            for candidate in GeneratedScenario.objects(team_id=slack_team_id, status="approved").order_by("-approved_at"):
                if AIExerciseRun.objects(scenario=candidate).first() is None:
                    approved_ai_scenario = candidate
                    break

        if active_run is not None:
            from . import ai_drill_v2

            # Keep this the one real "Live" location for the run, so a
            # later auto-completion can update THIS message in place
            # instead of posting a separate new one.
            if top_channel_id and top_message_ts:
                active_run.live_channel_id, active_run.live_message_ts = top_channel_id, top_message_ts
                active_run.save()
            card = ai_drill_v2.build_run_status_card(active_run, active_run.scenario)
        elif approved_ai_scenario:
            from . import ai_drill_v2

            card = ai_drill_v2.build_trigger_picker_card(approved_ai_scenario)
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
            if mod_id in ("bc", "cyber", "privacy") and mod_id not in selected:
                state["assigned"].pop(mod_id, None)
        persistence_v2.save_admins_state(slack_team_id, state["assigned"])
        _redraw_admins(response_url, bot_token, current_user_id, state)
        return

    if action_id == "v2_admin_take_all":
        state = read_admins_state(message_blocks)
        for mod in state.get("selected_modules") or ("bc", "cyber", "privacy"):
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

    # "Continue" on Admins -- advances to Threat Approval (Agent 1)
    # instead of straight to BIA/BCP upload, since the threat profile
    # only needs the sign-up form data, not an uploaded plan.
    if action_id == "v2_admins_done":
        from . import threat_profile_review_v2

        _replace_message(
            response_url,
            with_nav_bar_v2(threat_profile_review_v2.build_review_card(slack_team_id, active_module=threat_profile_review_v2.read_active_module(message_blocks)), "threat_review"),
            bot_token=bot_token,
            channel_id=top_channel_id,
            message_ts=top_message_ts,
        )
        return

    # Clicking the "Upload & Analysis" nav tab directly still jumps
    # straight there, independent of where Admins' own Continue goes.
    # A plan already on file means they already answered "Yes" by
    # uploading it -- skip straight to the status screen instead of
    # asking again.
    if action_id == "v2_nav_jump__bia_upload":
        from .bia_upload_v2_data import build_bia_question_card, _latest_plan

        if slack_team_id and _latest_plan(slack_team_id) is not None:
            _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        else:
            # Save the location here too (not just once a plan exists) so
            # a draft generated from the "No BCP" branch, which starts
            # from this exact screen, can still auto-refresh when ready.
            _replace_message(response_url, with_nav_bar_v2(build_bia_question_card(), "bia_upload"))
            if slack_team_id and top_channel_id and top_message_ts:
                persistence_v2.save_bia_upload_card_location(slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_bia_have_doc_yes":
        # A real "Yes" click (either "Yes, I have it" on the first
        # screen, or "I have it now" on the GRC-options screen -- same
        # action_id, same meaning) -- the only trigger that sends the
        # upload-prompt DM. "Check again" below shares the same redraw
        # but must NOT re-send it.
        from .bia_upload_v2_data import send_upload_prompt_dm

        if slack_team_id and current_user_id and bot_token:
            send_upload_prompt_dm(slack_team_id, current_user_id, bot_token)
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        return

    if action_id == "v2_bia_check_again":
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
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

    if action_id == "v2_bia_add_service":
        from .bia_upload_v2_data import _latest_plan
        from .add_service_modal_v2 import open_modal

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
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        return

    # "Make changes" -- loops back to the upload step, same shape as the
    # BIA/BCP-available No-branch and the org-details approval No-branch
    # elsewhere in this flow (sir's flowchart: "No -- again change and show").
    if action_id == "v2_ai_changes":
        _redraw_bia_upload(response_url, slack_team_id, top_channel_id, top_message_ts, current_user_id, bot_token)
        return

    if action_id == "v2_ai_approve":
        from plans.models import Plan

        plan = Plan.objects(slack_team_id=slack_team_id, is_latest=True).order_by("-created_at").first() if slack_team_id else None
        if plan is not None and plan.resilience_map_status != "approved":
            plan.resilience_map_status = "approved"
            plan.save()
        # Nav order is Upload & Analysis -> Teams -> Threat Profile, so
        # Approve continues to Teams next, not straight to Threat Profile.
        #
        # Posts Teams as a NEW message instead of editing this one in
        # place -- sir's call: editing in place keeps the viewer's
        # scroll position wherever they clicked (often partway down a
        # long card), a real Slack client behavior the API can't
        # override. A new message pulls Slack's scroll down to it,
        # landing at its own top instead. Falls back to the old
        # in-place edit if the repost itself fails for any reason.
        try:
            from .slack_client import SlackApiError, _call

            people = get_workspace_people(bot_token)
            teams_card = with_nav_bar_v2(build_teams_card(persistence_v2.load_teams_state(slack_team_id), people, slack_team_id=slack_team_id), "teams")
            new_msg = _call("chat.postMessage", bot_token, channel=top_channel_id, **teams_card)
            new_ts = new_msg.get("ts", "")
            if not new_ts:
                raise SlackApiError("no ts returned")
            if top_message_ts:
                _call("chat.delete", bot_token, channel=top_channel_id, ts=top_message_ts)
            if slack_team_id:
                persistence_v2.save_teams_card_location(slack_team_id, top_channel_id, new_ts)
        except SlackApiError:
            logger.exception("Couldn't repost Teams as a new message for team %s -- falling back to in-place edit", slack_team_id)
            _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id), slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_nav_jump__teams":
        _redraw_teams(response_url, bot_token, persistence_v2.load_teams_state(slack_team_id), slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id == "v2_teams_open_portal":
        # Signs a short-lived launch token from the real team_id + the
        # real clicking user's slack_user_id Slack just handed us on this
        # very click (teams_portal/views.py verifies this token server
        # side before ever DMing an OTP) -- sent as a real DM (not an
        # in-channel ephemeral reply) per sir's call, so Command Center
        # doesn't show this click to anyone, including the clicker --
        # it just lands in their own DM with the bot instead.
        from django.conf import settings

        from teams_portal.views import make_launch_token

        if slack_team_id and current_user_id and bot_token:
            launch_token = make_launch_token(slack_team_id, current_user_id)
            portal_url = f"{settings.FRONTEND_URL}/teams-portal?token={launch_token}"
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "channel": top_channel_id,
                    "text": "Open Teams on website",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Opens for you only, expires in 5 minutes -- we'll DM you a code to confirm it's really you."},
                            "accessory": {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Open Teams on website", "emoji": True},
                                "url": portal_url,
                                "style": "primary",
                            },
                        }
                    ],
                },
                timeout=10,
            )
        return

    if action_id.startswith("v2_team_priority_tab__"):
        state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        _, team_id, priority = action_id.split("__", 2)
        state["expanded_team"] = team_id
        state["active_priority"] = priority
        state["active_role_page"] = 1
        _redraw_teams(response_url, bot_token, state, slack_team_id, top_channel_id, top_message_ts)
        return

    if action_id.startswith("v2_team_role_page_prev__") or action_id.startswith("v2_team_role_page_next__"):
        state = read_teams_state(message_blocks)
        saved = persistence_v2.load_teams_state(slack_team_id)
        state["teams"], state["resp"] = saved["teams"], saved["resp"]
        current_page = int(action.get("value") or "1")
        delta = -1 if action_id.startswith("v2_team_role_page_prev__") else 1
        state["active_role_page"] = max(1, current_page + delta)
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
            # Stored as UTC (so it stays comparable/consistent in the
            # database), but shown to the person in IST -- the admin's
            # real workspace timezone -- not the raw UTC they clicked in.
            now_ist = now + datetime.timedelta(hours=5, minutes=30)
            card = role_welcome_v2.build_ack_done_card(now_ist.strftime("%d %b %Y, %H:%M IST"))

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
        _redraw_threats(response_url, state, slack_team_id, bot_token, top_channel_id, top_message_ts)
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
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_timing_picker_card(scenario, training_mode), "trigger"))
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
        if top_channel_id and top_message_ts:
            run.live_channel_id, run.live_message_ts = top_channel_id, top_message_ts
            run.save()
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_run_status_card(run, scenario), "trigger"))
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
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_run_status_card(run, scenario), "trigger"))
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

    if action_id.startswith("v2_scenario_phase_tab__"):
        from .scenario_v2_data import build_scenario_review_card
        from .models_v2 import GeneratedScenario

        parts = action.get("value", "").split("|")
        doc_id = parts[0] if parts else ""
        phase = parts[1] if len(parts) > 1 else ""
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        doc = GeneratedScenario.objects(id=doc_id).first()
        if not doc:
            return
        breadcrumb = f"{doc.threat_label}  ›  {doc.incident_name}  ›  {doc.cause_name}"
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb, active_phase=phase, consequences_page=page), "org_threats"))
        return

    if action_id == "v2_scenario_consequences_page":
        from .scenario_v2_data import _CONSEQUENCES_TAB, build_scenario_review_card
        from .models_v2 import GeneratedScenario

        doc_id, _, page_str = action.get("value", "").partition("|")
        doc = GeneratedScenario.objects(id=doc_id).first()
        if not doc:
            return
        page = int(page_str) if page_str.isdigit() else 0
        breadcrumb = f"{doc.threat_label}  ›  {doc.incident_name}  ›  {doc.cause_name}"
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(build_scenario_review_card(doc, breadcrumb, active_phase=_CONSEQUENCES_TAB, consequences_page=page), "org_threats"))
        return

    if action_id == "v2_scenario_open_portal":
        # Same real launch-token -> Slack-DM-OTP pattern as
        # v2_teams_open_portal, just scoped to one scenario instead of a
        # team's whole roster -- so phases/injects/decisions (too small
        # to read in the Slack card) can be reviewed properly on the
        # website, with the approval posted back into this same channel.
        from django.conf import settings

        from scenario_portal.views import make_launch_token

        scenario_doc_id = action.get("value", "")
        if slack_team_id and current_user_id and bot_token and scenario_doc_id:
            launch_token = make_launch_token(slack_team_id, current_user_id, scenario_doc_id, top_channel_id or "")
            portal_url = f"{settings.FRONTEND_URL}/scenario-portal?token={launch_token}"
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "channel": top_channel_id,
                    "text": "Open scenario on website",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Opens for you only -- we'll DM you a code to confirm it's really you."},
                            "accessory": {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Open scenario on website", "emoji": True},
                                "url": portal_url,
                                "style": "primary",
                            },
                        },
                    ],
                },
                timeout=10,
            )
        return

    if action_id == "v2_scenario_approve":
        import datetime

        from . import ai_drill_v2
        from .models_v2 import GeneratedScenario

        doc = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not doc:
            return

        doc.status = "approved"
        doc.approved_by_slack_user_id = current_user_id
        doc.approved_at = datetime.datetime.utcnow()
        doc.save()
        if response_url:
            # Approve hands straight off to the Trigger tab's own
            # training-mode question (ai_drill_v2.build_trigger_picker_card)
            # instead of re-showing that same question embedded in the
            # review card -- that card already existed, it just wasn't
            # being used anywhere (sir's call: one training-mode prompt,
            # same place the fixed-plan flow already asks it, not two).
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_trigger_picker_card(doc), "trigger"))
        return

    if action_id == "v2_scenario_goto_trigger":
        # Coming back to an already-approved scenario (e.g. re-opening
        # the same Incident on Threat Mapping) has nothing to re-approve
        # -- just hands off to the same Trigger screen Approve itself
        # goes to, so there's still a way forward (there's no separate
        # "Trigger" nav tab to click instead any more).
        from . import ai_drill_v2
        from .models_v2 import GeneratedScenario

        doc = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not doc:
            return
        if response_url:
            _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_trigger_picker_card(doc), "trigger"), bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_scenario_back_to_threats":
        # The Scenario Review screen replaces the Threat Mapping message
        # entirely (same message, swapped via chat.update/response_url),
        # so there was no way back to it without this -- rebuilds the
        # exact Module/Criticality/Threat/Incident position this
        # scenario was generated from, from the scenario doc's own real
        # module/threat_id/incident_id, not a guess.
        from . import org_setup_v2
        from .models_v2 import GeneratedScenario, OrgThreatProfile
        from .threats_v2_data import THREATS

        doc = GeneratedScenario.objects(id=action.get("value", "")).first()
        if not doc or not response_url:
            return

        saved = persistence_v2.load_threats_state(slack_team_id) if slack_team_id else {"fixed": {}, "custom": []}
        state = {"fixed": saved.get("fixed", {}), "custom": saved.get("custom", []), "form": None}
        state["active_module"] = doc.module
        state["active_threat"] = doc.threat_id
        state["active_incident"] = doc.incident_id

        default_crit = None
        if slack_team_id:
            from plans.threat_ranking import rank_threats

            approved_profile = OrgThreatProfile.objects(team_id=slack_team_id, status="approved").first()
            base_threats = approved_profile.threats if approved_profile else THREATS
            threats = rank_threats(slack_team_id, base_threats)
            default_crit = next((t["default_crit"] for t in threats if t["key"] == doc.threat_id), None)
        state["active_crit"] = state["fixed"].get(doc.threat_id, default_crit)

        profile = org_setup_v2.load_profile(slack_team_id) if slack_team_id else None
        card = with_nav_bar_v2(build_org_threats_card(state, profile, team_id=slack_team_id), "org_threats")
        _replace_message(response_url, card, bot_token, top_channel_id, top_message_ts)
        return

    if action_id == "v2_ai_drill_overview":
        from . import ai_drill_v2
        from .models_v2 import AIExerciseRun

        run = AIExerciseRun.objects(id=action.get("value", "")).first()
        if not run:
            return
        _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_drill_overview_card(run), "trigger"), bot_token=bot_token, channel_id=top_channel_id, message_ts=top_message_ts)
        return

    if action_id == "v2_ai_drill_team_breakdown":
        from . import ai_drill_v2
        from .models_v2 import AIExerciseRun

        run = AIExerciseRun.objects(id=action.get("value", "")).first()
        if not run:
            return
        _replace_message(response_url, with_nav_bar_v2(ai_drill_v2.build_drill_team_breakdown_card(run), "trigger"), bot_token=bot_token, channel_id=top_channel_id, message_ts=top_message_ts)
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


    if action_id.startswith("v2_nav_jump__"):
        # Nav tabs for steps not built yet -- nothing to show, leave the
        # current card as-is rather than erroring or going blank.
        return
