import json
import logging
import threading

import mongoengine
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from cards.intro_card_v2 import send_intro_dm
from cards.loader import load_card
from cards.slack_client import SlackApiError, publish_home_card
from commands.slack_signature import SlackSignatureError, verify_slack_signature
from plans.intake import handle_dm_message_event
from workspaces.models import Workspace, get_bot_token

from .models import ProcessedSlackEvent

logger = logging.getLogger(__name__)


def _handle_dm_message_then_refresh_wizard(event: dict, team_id: str, bot_token: str) -> None:
    """
    Wraps plans.intake.handle_dm_message_event (unmodified) so a DM
    upload finishing also pushes a fresh Upload & Analysis card to the
    new wizard, instead of the admin having to manually re-click
    "Check again" to see a file that finished processing minutes ago.
    Lives here, not in plans/intake.py, so that file stays untouched.
    """
    handle_dm_message_event(event, team_id, bot_token)

    try:
        from cards.bia_upload_v2_data import build_bia_upload_card
        from cards.nav_v2 import with_nav_bar_v2
        from cards.persistence_v2 import load_bia_upload_card_location
        from cards.slack_client import SlackApiError, _call

        location = load_bia_upload_card_location(team_id)
        channel_id, message_ts = location.get("channel_id", ""), location.get("message_ts", "")
        if channel_id and message_ts:
            card = with_nav_bar_v2(build_bia_upload_card(team_id), "bia_upload")
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
    except SlackApiError:
        logger.exception("Couldn't refresh Upload & Analysis card after a DM upload for team %s", team_id)
    except Exception:
        logger.exception("Unexpected error refreshing Upload & Analysis card for team %s", team_id)


@csrf_exempt
@require_POST
def slack_events(request):
    """
    Request URL for Slack's Events API, set in the Slack app under Event
    Subscriptions. Slack only allows one Request URL per app, so every
    subscribed event type (app_home_opened, message.im, ...) is routed
    from here rather than one endpoint per feature.
    """
    try:
        verify_slack_signature(request)
    except SlackSignatureError:
        return JsonResponse({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    # Slack's one-time handshake when you first save the Request URL.
    if payload.get("type") == "url_verification":
        return JsonResponse({"challenge": payload.get("challenge", "")})

    if payload.get("type") == "event_callback":
        event_id = payload.get("event_id", "")
        if event_id and not _claim_event(event_id):
            # Already handled this one -- Slack retried because our first
            # response was too slow, not because anything is actually new.
            return JsonResponse({"ok": True})

        event = payload.get("event", {})
        # Which client workspace this event belongs to -- top-level on the
        # envelope, not inside "event". Everything downstream must use
        # THIS workspace's bot token, never a different client's.
        team_id = payload.get("team_id", "")
        bot_token = get_bot_token(team_id)

        if event.get("type") == "app_home_opened" and event.get("tab") == "home":
            _handle_app_home_opened(event, team_id, bot_token)

        elif event.get("type") == "team_join":
            _handle_team_join(event, team_id, bot_token)

        elif (
            event.get("type") == "message"
            and event.get("files")
            and "bot_id" not in event
            and event.get("subtype") != "bot_message"
        ):
            # Real plan intake (B1/B2) -- any DM or channel message with
            # a file attached gets parsed. Posts its own confirmation
            # message (plans/intake.py) independent of any wizard.
            #
            # Backgrounded: this runs text extraction + two AI calls
            # (Gemini structured extraction, NVIDIA resilience-map
            # extraction) which can take well over Slack's own ~3s
            # expectation for an Events API response (confirmed live --
            # a real upload's confirmation took ~5 minutes because this
            # was blocking the HTTP response the whole time). Same
            # fire-and-forget fix as cards/views.py uses for
            # interactivity.
            threading.Thread(
                target=_handle_dm_message_then_refresh_wizard, args=(event, team_id, bot_token), daemon=True
            ).start()

    # Slack only cares that we returned 200 quickly; the real work above
    # is fire-and-forget from its point of view.
    return JsonResponse({"ok": True})


def _claim_event(event_id: str) -> bool:
    """
    Atomically records that we're handling this event_id. Returns True the
    first time (go ahead and process it), False on any later attempt
    (already claimed -- a Slack retry, skip it).
    """
    try:
        ProcessedSlackEvent(event_id=event_id).save(force_insert=True)
        return True
    except mongoengine.errors.NotUniqueError:
        return False


def _handle_team_join(event, team_id, bot_token):
    """
    Fires the moment someone accepts the workspace invite link -- before
    any admin has assigned them a role. Sends the general orientation
    card (intro_card_v2); the real role card comes later, separately,
    once an admin actually staffs them in Configure Teams.
    """
    user = event.get("user", {})
    slack_user_id = user.get("id", "")
    # Slack sometimes sends team_join for bots/deactivated placeholders --
    # skip those, there's nobody real to welcome.
    if not slack_user_id or user.get("is_bot") or user.get("deleted"):
        return

    recipient_name = user.get("real_name") or user.get("name") or "there"
    workspace = Workspace.objects(team_id=team_id).first()
    org_name = workspace.team_name if workspace else ""
    send_intro_dm(slack_user_id, recipient_name, org_name, bot_token)


def _handle_app_home_opened(event, team_id, bot_token):
    slack_user_id = event.get("user", "")
    user = User.objects(slack_account__slack_user_id=slack_user_id).first()
    workspace = Workspace.objects(team_id=team_id).first()

    org_name = workspace.team_name if workspace else ""
    person_name = user.name if user else ""
    card = load_card("25-app-home.json", org_name=org_name, person_name=person_name)

    try:
        publish_home_card(slack_user_id, card, bot_token)
    except SlackApiError:
        logger.exception("Failed to publish Slack Home tab for user %s", slack_user_id)
