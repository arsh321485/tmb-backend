import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from commands.slack_signature import SlackSignatureError, verify_slack_signature

from .interactivity import handle_block_action


@csrf_exempt
@require_POST
def slack_interactivity(request):
    """
    Request URL for Slack's "Interactivity & Shortcuts", set in the Slack
    app dashboard. Slack POSTs here whenever someone clicks a button,
    picks a radio option, or checks a box in one of our cards -- as
    form-encoded data with a single "payload" field containing JSON.
    """
    try:
        verify_slack_signature(request)
    except SlackSignatureError:
        return JsonResponse({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    if payload.get("type") == "block_actions":
        handle_block_action(payload)

    # Slack just needs a fast 200; the real work above already happened
    # (posting the next card), it isn't part of this response.
    return JsonResponse({"ok": True})
