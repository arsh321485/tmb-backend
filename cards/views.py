import json
import logging
import threading

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from commands.slack_signature import SlackSignatureError, verify_slack_signature

from .interactivity import handle_block_action, handle_view_submission

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def slack_interactivity(request):
    """
    Request URL for Slack's "Interactivity & Shortcuts", set in the Slack
    app dashboard. Slack POSTs here whenever someone clicks a button,
    picks a radio option, or checks a box in one of our cards -- as
    form-encoded data with a single "payload" field containing JSON.

    Slack only waits 3 seconds for this response. The actual handling
    (a MongoDB lookup, then a views.update/chat.postMessage call to
    Slack) can take longer than that, especially on a slow host -- when
    it does, Slack shows the user "We had some trouble connecting" even
    though the update still lands right after (confirmed live: the
    modal updated correctly despite the warning). Fix: acknowledge Slack
    immediately and do the real work in a background thread instead of
    before responding, so the 3-second window is never at risk.
    """
    try:
        verify_slack_signature(request)
    except SlackSignatureError:
        return JsonResponse({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    payload_type = payload.get("type")
    if payload_type == "block_actions":
        _run_in_background(handle_block_action, payload)
    elif payload_type == "view_submission":
        _run_in_background(handle_view_submission, payload)

    return JsonResponse({"ok": True})


def _run_in_background(fn, payload: dict) -> None:
    def _wrapped():
        try:
            fn(payload)
        except Exception:
            logger.exception("Unhandled error in background interactivity handler %s", fn.__name__)

    threading.Thread(target=_wrapped, daemon=True).start()
