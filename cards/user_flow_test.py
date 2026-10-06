"""
Participant-side (user_screen design) test flow -- hardcoded, one-off,
same as the admin side's very first "just show me the mockup live in
real Slack" step. No database, no real exercise behind this: matches
cards/onboarding_v2.py's early days before Steps 2-5 (real team/role
storage, join detection, real DMs) exist.

Routed from cards/interactivity_v2.py via the "v2_test_" action_id
prefix -- kept in its own file since this is participant-side, not
admin-side (interactivity_v2.py is entirely admin cards otherwise).
"""

import logging

from .slack_client import SlackApiError, _call
from .user_nav_test import with_nav_bar_user_test

logger = logging.getLogger(__name__)


def _welcome_body() -> list:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": ":dart: Getting started", "emoji": True}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Welcome, Sofia. You're in as IR Lead.*\nDana Okafor started _Ransomware Containment_ in #ir-war-room. This channel is where the drill runs -- every action is a button.",
            },
        },
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "*YOUR RESPONSIBILITIES*"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "1. Triage the first alert and declare severity\n2. Own the containment decision — isolate vs. quarantine the hosts\n3. Brief the command center on status within 15 minutes\n4. Hand privacy the technical facts — attest what left the environment",
            },
        },
        {
            "type": "actions",
            "block_id": "test_join_exercise",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":arrow_forward: Join the exercise", "emoji": True},
                    "action_id": "v2_test_join_exercise",
                    "style": "danger",
                    "value": "join",
                }
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Every step is a button — no commands to memorize."}]},
    ]


def _join_screen_body() -> list:
    return [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":clock1: Exercise started · this is a drill — do not action externally · 00:00"}],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Inject 1 · Detection*  ·  `HIGH`\nEDR flags mass file encryption on 14 endpoints in the Lab subnet. Alarms are firing now.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Tomas Kruger*  ·  _SOC Analyst_  ·  01:40\nConfirmed — encryption signature matches a known ransomware variant. Isolating the 14 hosts from the network.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":red_circle: *Your move, Sofia* — the team is waiting on the IR Lead. Pick one, or just type your own update below.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_sitrep_quick",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Declaring a Sev-1 — activating the IR bridge now.", "emoji": True},
                    "action_id": "v2_test_sitrep__sev1",
                    "value": "sev1",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Need the impact scope from SOC first.", "emoji": True},
                    "action_id": "v2_test_sitrep__scope",
                    "value": "scope",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "On it — pulling the affected user list.", "emoji": True},
                    "action_id": "v2_test_sitrep__pulling",
                    "value": "pulling",
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Or just type a normal message in this channel — that works too."}],
        },
    ]


def post_welcome(channel_id: str, bot_token: str) -> None:
    blocks = with_nav_bar_user_test(_welcome_body(), "welcome")
    try:
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=blocks, text="Welcome, Sofia. You are in as IR Lead.")
    except SlackApiError:
        logger.exception("Failed to post welcome test screen to %s", channel_id)


def post_join_exercise_screen(channel_id: str, bot_token: str) -> None:
    """
    What appears in #ir-war-room right after clicking "Join the exercise"
    on the welcome card -- matches the user_screen mockup's second screen
    (detection inject, a teammate's message, then a "your move" quick-reply
    prompt for the participant).
    """
    blocks = with_nav_bar_user_test(_join_screen_body(), "join")
    try:
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=blocks, text="Your move, Sofia — the team is waiting on the IR Lead.")
    except SlackApiError:
        logger.exception("Failed to post join-exercise test screen to %s", channel_id)


def post_sitrep_ack(channel_id: str, bot_token: str, choice_label: str) -> None:
    """Simple echo confirming the quick-reply was picked -- honest that nothing real is scored yet."""
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=f":white_check_mark: Logged: \"{choice_label}\" — _test only, not scored yet._",
        )
    except SlackApiError:
        logger.exception("Failed to post sitrep ack to %s", channel_id)


def _decision_body() -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Priya Adeyemi*  ·  _Identity & Access_  ·  03:10\nForcing a reset on the 14 users and revoking their sessions now.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Inject 2 · Second wave*  ·  `HIGH`\nThe same credentials hit the VPN an hour before the phishing click — the entry point may still be open.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*:red_circle: Decision required*\n*Isolate the 14 affected endpoints from the network now?*\nClinical VLAN is already separate. Isolating stops the spread but takes the Lab subnet offline.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_decision",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Isolate now — sever the Lab subnet immediately", "emoji": True},
                    "action_id": "v2_test_decision__isolate",
                    "style": "danger",
                    "value": "isolate",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Hold & monitor — watch for spread before cutting", "emoji": True},
                    "action_id": "v2_test_decision__hold",
                    "value": "hold",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Hand to Network Owner — give the call to James Whitfield", "emoji": True},
                    "action_id": "v2_test_decision__handoff",
                    "value": "handoff",
                },
            ],
        },
    ]


DECISION_REACTIONS = {
    "isolate": ("James Whitfield", "Network Owner", "Copy — severing the Lab subnet now. Clinical systems unaffected. Cut confirmed."),
    "hold": ("Dana Okafor", "Facilitator", "Logged: holding. Note for the hot-wash — spread risk stays open while you monitor."),
    "handoff": ("James Whitfield", "Network Owner", "I've got it — isolating the Lab subnet on your call. Cutting now."),
}


def post_decision_screen(channel_id: str, bot_token: str) -> None:
    try:
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_decision_body(), text="Decision required — isolate the 14 affected endpoints now?")
    except SlackApiError:
        logger.exception("Failed to post decision test screen to %s", channel_id)


def post_decision_reaction(channel_id: str, bot_token: str, choice: str) -> None:
    """Echo + teammate reaction, matching the mockup's per-choice response -- test only, nothing scored."""
    name, role, text = DECISION_REACTIONS.get(choice, ("", "", ""))
    if not text:
        return
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=f":white_check_mark: Decision logged — _test only, not scored yet._\n*{name}*  ·  _{role}_\n{text}",
        )
    except SlackApiError:
        logger.exception("Failed to post decision reaction to %s", channel_id)
    post_ack_screen(channel_id, bot_token)


def _ack_body() -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Inject 3 · Possible data loss*  ·  `MED`\nForensics find a staging archive of patient records on the encrypted share — privacy may need to be told.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*:lock: Action needed*\n*Forensics found patient records on the encrypted share.*\nPrivacy may need to be notified. Acknowledge and hand this to Privacy Counsel to start the 72-hour clock.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_ack",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":arrow_right: Acknowledge & hand to Privacy", "emoji": True},
                    "action_id": "v2_test_ack_confirm",
                    "style": "danger",
                    "value": "ack",
                }
            ],
        },
    ]


def post_ack_screen(channel_id: str, bot_token: str) -> None:
    try:
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_ack_body(), text="Inject 3 — possible data loss. Action needed.")
    except SlackApiError:
        logger.exception("Failed to post ack test screen to %s", channel_id)


def post_ack_reaction(channel_id: str, bot_token: str, privacy_bridge_channel_id: str = "") -> None:
    """
    Mockup reaction: Marco Castellanos confirms the 72-hour clock started
    and opens the privacy bridge. Test only -- doesn't actually open
    anything real yet, just echoes the line and (if we know the real
    #privacy-bridge channel) points at it for real.
    """
    bridge_mention = f" <#{privacy_bridge_channel_id}>" if privacy_bridge_channel_id else " #privacy-bridge"
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=(
                ":white_check_mark: Acknowledged & handed to Privacy — _test only, not scored yet._\n"
                f"*Marco Castellanos*  ·  _Legal Liaison_\nReceived — that starts our 72-hour clock. "
                f"Opening the privacy bridge{bridge_mention}; I'll need your attestation there."
            ),
        )
    except SlackApiError:
        logger.exception("Failed to post ack reaction to %s", channel_id)
    post_wrapup_and_debrief(channel_id, bot_token)


def _debrief_body() -> list:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": ":page_facing_up: Debrief · your results", "emoji": True}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Strong, decisive containment run.*\nYou ran the bridge well and contained early. One timing gap to close — legal was looped in slightly after containment.",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Illustrative numbers only, copied from the mockup (1m 12s MTTA, 3 decisions, 4 injects, grade B+) "
                        "— this preview has no real scoring engine, so nothing here was actually measured. Real scoring "
                        "needs the exercise-orchestration backend, which isn't built yet._"
                    ),
                }
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Strengths*\n:white_check_mark: Declared Sev-1 within 72s of the first alert\n:white_check_mark: Isolated affected hosts before any lateral spread",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*One gap*\nLegal looped in ~4 min after containment — your mapped action says 15 min, so this passed, but privacy wanted it sooner.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_debrief_report",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":page_facing_up: View full after-action report", "emoji": True},
                    "action_id": "v2_test_debrief_report",
                    "style": "danger",
                    "value": "report",
                }
            ],
        },
    ]


def post_wrapup_and_debrief(channel_id: str, bot_token: str) -> None:
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=(
                "*Kenji Sato*  ·  _Endpoint Owner_  ·  09:02\nEDR is reporting clean on all 14 hosts. "
                "Two that were offline are blocked at the switch.\n\n:hourglass_flowing_sand: _Facilitator is wrapping the exercise…_"
            ),
        )
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_debrief_body(), text="Debrief — your results")
    except SlackApiError:
        logger.exception("Failed to post wrap-up/debrief to %s", channel_id)


def _evidence_request_body() -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*:lock: Evidence request · Privacy Counsel*\n*What can you attest to about the exfiltration?*\nChoose the option that best matches your forensic findings. This will be attached to the regulator notification.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_attest",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confirmed exfiltration — egress logs show the export left", "emoji": True},
                    "action_id": "v2_test_attest__confirmed",
                    "style": "danger",
                    "value": "confirmed",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Access only — records viewed, nothing transferred", "emoji": True},
                    "action_id": "v2_test_attest__access_only",
                    "value": "access_only",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cannot determine — logging gap at the vendor edge", "emoji": True},
                    "action_id": "v2_test_attest__unknown",
                    "value": "unknown",
                },
            ],
        },
    ]


ATTEST_LABELS = {
    "confirmed": "Confirmed exfiltration",
    "access_only": "Access only, no exfil",
    "unknown": "Cannot determine",
}


def post_privacy_bridge_opened(channel_id: str, bot_token: str) -> None:
    """
    Fires the moment IR acknowledges Inject 3 in #ir-war-room -- opens the
    real #privacy-bridge channel with the 72-hour clock card, Marco's
    request, and the evidence-request card. Test only, same hardcoded
    "Sofia" participant as the rest of this flow.
    """
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=":hourglass_flowing_sand: Privacy bridge opened · Vendor Processor Breach · 08:40",
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=(
                ":clock1: *72-hour notification clock*  ·  `RUNNING`\n"
                "Awareness established at 08:40. Marco Castellanos is lead. You've been pulled in to provide the "
                "technical facts behind the breach assessment.\n"
                "*68h 12m* remaining  ·  *4,180* records at risk  ·  *3* jurisdictions"
            ),
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text="*Marco Castellanos*  ·  _Legal Liaison_  ·  08:49\nSofia — I need one thing from IR: can you confirm what actually left the environment, and when we knew?",
        )
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_evidence_request_body(), text="Evidence request — what can you attest to about the exfiltration?")
    except SlackApiError:
        logger.exception("Failed to post privacy bridge open sequence to %s", channel_id)


def post_attest_reaction(channel_id: str, bot_token: str, choice: str) -> None:
    label = ATTEST_LABELS.get(choice, choice)
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=f":closed_lock_with_key: IR attestation logged · {label} — _You · attached to the breach record (test only)_",
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*:page_facing_up: Your statement*\nYour attestation, the detection timestamp and the containment timeline have been written into the regulator notification. Check it before Marco files.",
                    },
                },
                {
                    "type": "actions",
                    "block_id": "test_ir_statement",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": ":arrow_right: Review & approve my section", "emoji": True},
                            "action_id": "v2_test_statement_approve",
                            "style": "danger",
                            "value": "approve",
                        }
                    ],
                },
            ],
            text="Your statement — drafted for you.",
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text="*Priya Adeyemi*  ·  _Identity & Access_  ·  09:04\nFlagging for the hot-wash: vendor edge logging is a gap we own, not the processor.",
        )
    except SlackApiError:
        logger.exception("Failed to post attest reaction to %s", channel_id)


def post_statement_approved(channel_id: str, bot_token: str) -> None:
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=":white_check_mark: You approved the IR section — sent back to Privacy Counsel _(test only)_.",
        )
    except SlackApiError:
        logger.exception("Failed to post statement approval to %s", channel_id)


def _announcement_body() -> list:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": ":zap: Announcement", "emoji": True}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Drills happen in chat now*\nNo offsite day, no slide deck. Your admin maps each responsibility to one exact action, and a drill asks you for that action — one card at a time, in your war-room channel, in 20–40 minutes.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_show_assignments",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":arrow_right: Show my assignments", "emoji": True},
                    "action_id": "v2_test_show_assignments",
                    "style": "danger",
                    "value": "show",
                }
            ],
        },
    ]


def post_general_announcement(channel_id: str, bot_token: str) -> None:
    try:
        _call("chat.postMessage", bot_token, channel=channel_id, text="TestMyPlan was added to the workspace.")
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_announcement_body(), text="Drills happen in chat now.")
    except SlackApiError:
        logger.exception("Failed to post general announcement to %s", channel_id)


def _drill_window_body() -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*:clock1: Next drill window*  ·  `OPEN`\nThursday, any time between 09:00 and 16:00. Pick a window and the drill will find you then.",
            },
        },
        {
            "type": "actions",
            "block_id": "test_drill_window",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Morning", "emoji": True},
                    "action_id": "v2_test_window__morning",
                    "value": "morning",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Early afternoon", "emoji": True},
                    "action_id": "v2_test_window__early_pm",
                    "value": "early_pm",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Late afternoon", "emoji": True},
                    "action_id": "v2_test_window__late_pm",
                    "value": "late_pm",
                },
            ],
        },
    ]


def post_show_assignments(channel_id: str, bot_token: str) -> None:
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=":busts_in_silhouette: You're *IR Lead* on the Incident Response Team _(test only, not a real assignment yet)_.\nTomas Kruger is your backup · also on the privacy bridge as Security Liaison.",
        )
        _call("chat.postMessage", bot_token, channel=channel_id, blocks=_drill_window_body(), text="Next drill window — pick one.")
    except SlackApiError:
        logger.exception("Failed to post assignments to %s", channel_id)


WINDOW_LABELS = {"morning": "Morning", "early_pm": "Early afternoon", "late_pm": "Late afternoon"}


def post_window_picked(channel_id: str, bot_token: str, choice: str) -> None:
    label = WINDOW_LABELS.get(choice, choice)
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=f":white_check_mark: Availability set · {label} — Thursday · you'll be paged in that window _(test only, no real drill scheduled)_.",
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text="*Kenji Sato*  ·  _Endpoint Owner_  ·  Tue 09:41\nDid mine in 22 minutes between meetings. Genuinely fine.",
        )
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*:page_facing_up: Your quarter*  ·  `UP 9 PTS`\n*3* drills taken  ·  *88* avg. score  ·  *1m 12s* avg. MTTA",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "_Illustrative numbers copied from the mockup — no real drills have run yet, so nothing here is actually measured._",
                        }
                    ],
                },
            ],
            text="Your quarter — illustrative numbers only.",
        )
    except SlackApiError:
        logger.exception("Failed to post window-picked follow-up to %s", channel_id)


def post_debrief_report_notice(channel_id: str, bot_token: str) -> None:
    """
    Honest version of the mockup's "full after-action report" -- same
    principle as report_modal_v2.py: this preview has no real scoring
    engine, so there's no real report to show, and the mockup's example
    numbers aren't reproduced here.
    """
    try:
        _call(
            "chat.postMessage",
            bot_token,
            channel=channel_id,
            text=(
                ":page_facing_up: *No real after-action report yet.* Full scoring, per-responsibility timing, and "
                "the detailed report need the exercise-orchestration backend, which hasn't been built yet — "
                "and no real exercise has run here to report on anyway."
            ),
        )
    except SlackApiError:
        logger.exception("Failed to post debrief report notice to %s", channel_id)
