"""
API for the website Teams-assignment page. Protected by a Slack-DM OTP
(see this app's models.py and cards/interactivity_v2.py's
v2_teams_open_portal handler) instead of email -- the launch link already
carries the real team_id + slack_user_id Slack handed us on the actual
button click, so the OTP only has to prove "the browser is the same
person who clicked", not figure out who they are.
"""

import datetime
import functools
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cards.models_v2 import Team, TeamMember
from cards.slack_client import SlackApiError, send_dm_text
from cards.slack_members_v2 import get_workspace_people
from cards.team_catalog_v2 import roles_for_team
from workspaces.models import get_bot_token

from .models import TeamsPortalOtp

_SIGNER_SALT = "teams_portal.launch_token"
# 15 minutes -- long enough to cover reading the Slack DM, typing the
# code, AND at least one "Resend code" round trip (which re-uses this
# same launch token) without the link itself going stale first.
_LAUNCH_TOKEN_MAX_AGE_SECONDS = 900
# 10 minutes -- real usage showed 5 was too tight once someone actually
# has to switch to Slack, read the DM, and type 6 digits back in.
_OTP_TTL_SECONDS = 600
_OTP_MAX_ATTEMPTS = 5


def make_launch_token(team_id: str, slack_user_id: str) -> str:
    """Called from cards/interactivity_v2.py's v2_teams_open_portal handler
    (the real Slack button click) -- never constructed anywhere else, so
    the team_id/slack_user_id inside it are always what Slack itself gave
    us for that click, not something the website could forge."""
    signer = signing.TimestampSigner(salt=_SIGNER_SALT)
    return signer.sign(f"{team_id}|{slack_user_id}")


def _read_launch_token(token: str) -> tuple[str, str] | None:
    signer = signing.TimestampSigner(salt=_SIGNER_SALT)
    try:
        value = signer.unsign(token, max_age=_LAUNCH_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    team_id, _, slack_user_id = value.partition("|")
    if not team_id or not slack_user_id:
        return None
    return team_id, slack_user_id


def _session_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        team_id = request.session.get("teams_portal_team_id")
        slack_user_id = request.session.get("teams_portal_slack_user_id")
        if not team_id or not slack_user_id:
            return Response({"error": "not_authenticated"}, status=401)
        return view_func(request, team_id, slack_user_id, *args, **kwargs)
    return wrapper


@never_cache
@api_view(["POST"])
def request_otp(request):
    """Step 1: website lands with ?token=... from the Slack button, posts
    it here. Verifies it, DMs a real 6-digit code to that exact Slack
    user (never an email), returns an opaque otp_id to carry into verify."""
    token = (request.data.get("token") or "").strip()
    parsed = _read_launch_token(token)
    if not parsed:
        return Response({"error": "invalid_or_expired_token"}, status=400)
    team_id, slack_user_id = parsed

    bot_token = get_bot_token(team_id)
    if not bot_token:
        return Response({"error": "workspace_not_installed"}, status=400)

    code = f"{secrets.randbelow(1_000_000):06d}"
    otp = TeamsPortalOtp(
        team_id=team_id,
        slack_user_id=slack_user_id,
        code_hash=make_password(code),
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(seconds=_OTP_TTL_SECONDS),
    )
    otp.save()

    try:
        send_dm_text(slack_user_id, f"Your TestMyPlan Teams code is *{code}* -- expires in 10 minutes.", bot_token)
    except SlackApiError:
        otp.delete()
        return Response({"error": "could_not_send_dm"}, status=502)

    return Response({"otp_id": str(otp.id)})


@never_cache
@api_view(["POST"])
def verify_otp(request):
    """Step 2: website posts {otp_id, code}. On a real match, starts a
    Django session scoped to that one team_id -- every other endpoint in
    this app requires this session and only ever reads/writes that
    team_id, never one the client names."""
    otp_id = (request.data.get("otp_id") or "").strip()
    code = (request.data.get("code") or "").strip()

    otp = TeamsPortalOtp.objects(id=otp_id).first() if otp_id else None
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
    request.session["teams_portal_team_id"] = otp.team_id
    request.session["teams_portal_slack_user_id"] = otp.slack_user_id
    return Response({"ok": True, "team_id": otp.team_id})


@never_cache
@api_view(["GET"])
@_session_required
def get_members(request, team_id, slack_user_id):
    """Real workspace people for the assignment picker -- same real list
    (not a mock) the Slack Teams card itself already uses."""
    bot_token = get_bot_token(team_id)
    people = get_workspace_people(bot_token)
    return Response({"members": people})


@never_cache
@api_view(["GET"])
@_session_required
def get_teams(request, team_id, slack_user_id):
    """Every real Team + its TeamMember rows for this workspace -- the
    exact documents cards/teams_v2_data.py's Teams card reads, so this
    is always in sync with Slack, not a separate copy of the data."""
    teams = []
    for team in Team.objects(team_id=team_id):
        # The real role list for this team always comes from the catalog
        # (team_catalog_v2.roles_for_team), same as the Slack Teams card
        # itself -- a TeamMember document only exists once someone has
        # actually been assigned, so a never-touched team would otherwise
        # show zero rows (nothing to click "Primary"/"Backup" on at all).
        existing_by_role = {m.role: m for m in TeamMember.objects(team=team)}
        members = [
            {
                "role": role["role"],
                "primary_slack_user_ids": list(existing_by_role[role["role"]].primary_slack_user_ids) if role["role"] in existing_by_role else [],
                "backup_slack_user_ids": list(existing_by_role[role["role"]].backup_slack_user_ids) if role["role"] in existing_by_role else [],
            }
            for role in roles_for_team(team.slug)
        ]
        teams.append({
            "id": str(team.id), "module": team.module, "slug": team.slug,
            "name": team.name, "is_mandatory": team.is_mandatory, "members": members,
        })
    return Response({"teams": teams})


@never_cache
@api_view(["POST"])
@_session_required
def set_role_assignment(request, team_id, slack_user_id):
    """Writes real Primary/Backup picks for one role -- the exact
    TeamMember fields the Slack Teams card reads, so a submission here
    shows up there the very next time that card renders, no sync step."""
    doc_team_id = (request.data.get("team_doc_id") or "").strip()
    role = (request.data.get("role") or "").strip()
    primary_slack_user_ids = list(request.data.get("primary_slack_user_ids") or [])
    backup_slack_user_ids = list(request.data.get("backup_slack_user_ids") or [])

    team = Team.objects(id=doc_team_id, team_id=team_id).first()
    if not team:
        return Response({"error": "team_not_found"}, status=404)

    if role not in {r["role"] for r in roles_for_team(team.slug)}:
        return Response({"error": "role_not_found"}, status=404)

    # First real assignment for this role creates its TeamMember row --
    # it only exists once someone's actually been picked (same lazy
    # creation persistence_v2.save_teams_state already does for the
    # Slack side), not pre-seeded for every catalog role up front.
    member = TeamMember.objects(team=team, role=role).first()
    if not member:
        member = TeamMember(team=team, role=role)

    member.primary_slack_user_ids = primary_slack_user_ids
    member.backup_slack_user_ids = backup_slack_user_ids
    member.save()
    return Response({"ok": True})
