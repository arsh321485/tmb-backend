import json
import logging

import mongoengine
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from commands.slack_signature import SlackSignatureError, verify_slack_signature
from plans.intake import handle_dm_message_event
from workspaces.models import get_bot_token

from .models import ProcessedSlackEvent
from .slack_client import SlackApiError, publish_home_view
from .view_builder import build_home_view

logger = logging.getLogger(__name__)


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
            _handle_app_home_opened(event, bot_token)

        elif (
            event.get("type") == "message"
            and event.get("channel_type") == "im"
            and "bot_id" not in event
            and event.get("subtype") != "bot_message"
        ):
            handle_dm_message_event(event, team_id, bot_token)

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


def _handle_app_home_opened(event, bot_token):
    slack_user_id = event.get("user", "")
    user = User.objects(slack_account__slack_user_id=slack_user_id).first()

    view = build_home_view(user)
    try:
        publish_home_view(slack_user_id, view, bot_token)
    except SlackApiError:
        logger.exception("Failed to publish Slack Home tab for user %s", slack_user_id)
