import json
import logging
import threading

import requests as http
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .handlers import dispatch
from .slack_signature import SlackSignatureError, verify_slack_signature

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def slack_command(request):
    """
    Request URL for the /testmyplan slash command, set in the Slack app under
    Slash Commands. Slack POSTs form-encoded data here every time someone
    types /testmyplan ... in a channel or DM.

    Slack only waits 3 seconds for the response here -- confirmed live:
    "/testmyplan gaps" failed with "operation_timeout" when a MongoDB
    query took a bit long. dispatch() usually is fast, but there's no
    guarantee of that (Mongo, or a future subcommand, doing something
    slower). Same fix as the interactivity endpoint: acknowledge
    instantly, do the real work in the background, then deliver the
    actual result via response_url instead of the initial response body.
    """
    try:
        verify_slack_signature(request)
    except SlackSignatureError:
        return JsonResponse({"error": "invalid_signature"}, status=401)

    command_text = request.POST.get("text", "")
    user_id = request.POST.get("user_id", "")
    channel_id = request.POST.get("channel_id", "")
    team_id = request.POST.get("team_id", "")
    response_url = request.POST.get("response_url", "")

    def _run_and_reply():
        try:
            result = dispatch(command_text, user_id, channel_id, team_id)
        except Exception:
            logger.exception("Unhandled error running /testmyplan %s", command_text)
            result = {"response_type": "ephemeral", "text": ":warning: Something went wrong running that command."}
        if response_url:
            try:
                http.post(response_url, json=result, timeout=10)
            except http.RequestException:
                logger.exception("Failed to deliver /testmyplan result via response_url")

    threading.Thread(target=_run_and_reply, daemon=True).start()
    # Slack requires *some* 200 response within 3s; an empty ack is fine
    # since the real message is delivered separately via response_url.
    return JsonResponse({"response_type": "ephemeral", "text": ":hourglass_flowing_sand: Working on it..."})


@csrf_exempt
@require_POST
def teams_command(request):
    """
    Placeholder for the Teams equivalent: a Bot Framework messaging endpoint
    that parses "@TestMyPlan run ..." style natural-language commands.
    Needs the Bot Framework SDK + registered bot before this can go live --
    stubbed here so the same dispatch() logic can be reused once that's set up.
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        body = {}

    text = body.get("text", "")
    # Teams messages look like "<at>TestMyPlan</at> run ransomware" -- strip
    # the mention before dispatching.
    for prefix in ("TestMyPlan", "<at>TestMyPlan</at>"):
        if text.strip().startswith(prefix):
            text = text.strip()[len(prefix):]
            break

    channel_id = body.get("conversation", {}).get("id", "")
    result = dispatch(text, body.get("from", {}).get("id", ""), channel_id)
    return JsonResponse({"type": "message", "text": result["text"]})
