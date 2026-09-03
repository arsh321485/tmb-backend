import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .handlers import dispatch
from .slack_signature import SlackSignatureError, verify_slack_signature


@csrf_exempt
@require_POST
def slack_command(request):
    """
    Request URL for the /testmyplan slash command, set in the Slack app under
    Slash Commands. Slack POSTs form-encoded data here every time someone
    types /testmyplan ... in a channel or DM.
    """
    try:
        verify_slack_signature(request)
    except SlackSignatureError:
        return JsonResponse({"error": "invalid_signature"}, status=401)

    command_text = request.POST.get("text", "")
    user_id = request.POST.get("user_id", "")
    channel_id = request.POST.get("channel_id", "")
    team_id = request.POST.get("team_id", "")

    result = dispatch(command_text, user_id, channel_id, team_id)
    return JsonResponse(result)


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
