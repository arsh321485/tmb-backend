import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from commands.slack_signature import SlackSignatureError, verify_slack_signature

from .slack_client import SlackApiError, publish_home_view
from .view_builder import build_home_view

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def slack_events(request):
    """
    Request URL for Slack's Events API, set in the Slack app under Event
    Subscriptions, subscribed to the `app_home_opened` bot event. Slack
    POSTs a JSON body here for every subscribed event.
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
        event = payload.get("event", {})
        if event.get("type") == "app_home_opened" and event.get("tab") == "home":
            _handle_app_home_opened(event)

    # Slack only cares that we returned 200 quickly; the real work above
    # is fire-and-forget from its point of view.
    return JsonResponse({"ok": True})


def _handle_app_home_opened(event):
    slack_user_id = event.get("user", "")
    user = User.objects(slack_account__slack_user_id=slack_user_id).first()

    view = build_home_view(user)
    try:
        publish_home_view(slack_user_id, view)
    except SlackApiError:
        logger.exception("Failed to publish Slack Home tab for user %s", slack_user_id)
