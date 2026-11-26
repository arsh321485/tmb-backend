"""
API for the website Scenario-review page -- same real shape as
teams_portal/views.py (Slack-button -> signed launch token -> Slack-DM OTP
-> scoped session), just for one GeneratedScenario instead of a team's
whole roster.
"""

import datetime
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cards.models_v2 import GeneratedScenario
from cards.slack_client import SlackApiError, send_dm_text
from workspaces.models import get_bot_token

from .models import ScenarioPortalOtp

_SIGNER_SALT = "scenario_portal.launch_token"
# Same reasoning as teams_portal's launch token: the OTP right after this
# is the real identity check, so a long window here just avoids the link
# going stale, without weakening security.
_LAUNCH_TOKEN_MAX_AGE_SECONDS = 86400
_OTP_TTL_SECONDS = 600
_OTP_MAX_ATTEMPTS = 5


def make_launch_token(team_id: str, slack_user_id: str, scenario_id: str, channel_id: str) -> str:
    """Called only from cards/interactivity_v2.py's v2_scenario_open_portal
    handler (the real Slack button click) -- team_id/slack_user_id/
    scenario_id/channel_id inside it are always what Slack itself gave us
    for that click, never something the website could forge."""
    signer = signing.TimestampSigner(salt=_SIGNER_SALT)
    return signer.sign(f"{team_id}|{slack_user_id}|{scenario_id}|{channel_id}")


def _read_launch_token(token: str) -> tuple[str, str, str, str] | None:
    signer = signing.TimestampSigner(salt=_SIGNER_SALT)
    try:
        value = signer.unsign(token, max_age=_LAUNCH_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    parts = value.split("|")
    if len(parts) != 4 or not parts[0] or not parts[1] or not parts[2]:
        return None
    team_id, slack_user_id, scenario_id, channel_id = parts
    return team_id, slack_user_id, scenario_id, channel_id


def _session_required(view_func):
    import functools

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        team_id = request.session.get("scenario_portal_team_id")
        slack_user_id = request.session.get("scenario_portal_slack_user_id")
        scenario_id = request.session.get("scenario_portal_scenario_id")
        channel_id = request.session.get("scenario_portal_channel_id", "")
        if not team_id or not slack_user_id or not scenario_id:
            return Response({"error": "not_authenticated"}, status=401)
        return view_func(request, team_id, slack_user_id, scenario_id, channel_id, *args, **kwargs)
    return wrapper


@never_cache
@api_view(["POST"])
def request_otp(request):
    token = (request.data.get("token") or "").strip()
    parsed = _read_launch_token(token)
    if not parsed:
        return Response({"error": "invalid_or_expired_token"}, status=400)
    team_id, slack_user_id, scenario_id, channel_id = parsed

    bot_token = get_bot_token(team_id)
    if not bot_token:
        return Response({"error": "workspace_not_installed"}, status=400)

    code = f"{secrets.randbelow(1_000_000):06d}"
    otp = ScenarioPortalOtp(
        team_id=team_id,
        slack_user_id=slack_user_id,
        scenario_id=scenario_id,
        channel_id=channel_id,
        code_hash=make_password(code),
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(seconds=_OTP_TTL_SECONDS),
    )
    otp.save()

    try:
        send_dm_text(slack_user_id, f"Your TestMyPlan scenario code is *{code}* -- expires in 10 minutes.", bot_token)
    except SlackApiError:
        otp.delete()
        return Response({"error": "could_not_send_dm"}, status=502)

    return Response({"otp_id": str(otp.id)})


@never_cache
@api_view(["POST"])
def verify_otp(request):
    otp_id = (request.data.get("otp_id") or "").strip()
    code = (request.data.get("code") or "").strip()

    otp = ScenarioPortalOtp.objects(id=otp_id).first() if otp_id else None
    if not otp or otp.verified:
        return Response({"error": "invalid_otp"}, status=400)
    if datetime.datetime.utcnow() > otp.expires_at:
        return Response({"error": "expired_otp"}, status=400)
    if otp.attempts >= _OTP_MAX_ATTEMPTS:
        return Response({"error": "too_many_attempts"}, status=429)

    if not check_password(code, otp.code_hash):
        otp.update(inc__attempts=1)
        return Response({"error": "incorrect_code"}, status=400)

    otp.update(set__verified=True)
    request.session["scenario_portal_team_id"] = otp.team_id
    request.session["scenario_portal_slack_user_id"] = otp.slack_user_id
    request.session["scenario_portal_scenario_id"] = otp.scenario_id
    request.session["scenario_portal_channel_id"] = otp.channel_id or ""
    return Response({"ok": True})


@never_cache
@api_view(["GET"])
@_session_required
def get_scenario(request, team_id, slack_user_id, scenario_id, channel_id):
    doc = GeneratedScenario.objects(id=scenario_id, team_id=team_id).first()
    if not doc:
        return Response({"error": "scenario_not_found"}, status=404)

    return Response({
        "scenario": {
            "id": str(doc.id),
            "threat_label": doc.threat_label or "",
            "incident_name": doc.incident_name or "",
            "cause_name": doc.cause_name or "",
            "phases": list(doc.phases or []),
            "injects": list(doc.injects or []),
            "consequence_injects": list(doc.consequence_injects or []),
            "status": doc.status,
        }
    })
