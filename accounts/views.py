import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_GET
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cards.onboarding_v2 import send_new_design_preview
from cards.user_channels_v2 import ensure_user_channels
from cards.user_flow_test import post_welcome as post_user_test_welcome
from cards.user_flow_test import post_general_announcement

from .models import SlackAccount, TeamsAccount, User
from workspaces.models import Workspace, claim_onboarding


def _is_valid_website_url(value: str) -> bool:
    """Any real http(s) address, dot in the domain or not -- just needs to actually be a URL, not a bare word."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@api_view(["POST"])
def save_pending_org_profile(request):
    """
    Website signup form (Organization Details step, BEFORE "Sign up with
    Slack") posts here. Returns a token; the frontend carries it through
    the Slack OAuth redirect (?profile_token=...) so slack_callback can
    find it again once we know which real Slack workspace this becomes.
    """
    import secrets as _secrets

    from cards.models_v2 import PendingOrgProfile

    data = request.data
    website_url = (data.get("website_url") or "").strip()
    if website_url and not _is_valid_website_url(website_url):
        return Response({"error": "invalid_website_url"}, status=400)

    token = _secrets.token_urlsafe(24)
    PendingOrgProfile(
        token=token,
        org_name=(data.get("org_name") or "").strip(),
        industry=(data.get("industry") or "").strip(),
        website_url=website_url,
        regions=list(data.get("regions") or []),
        regulations=list(data.get("regulations") or []),
    ).save()
    return Response({"token": token})


def _get_or_create_user(email, name=""):
    """
    mongoengine's QuerySet doesn't support Django's get_or_create(), so do
    the equivalent by hand: look the user up by email, create if missing.
    """
    user = User.objects(email=email).first()
    if user is None:
        user = User(email=email, name=name)
        user.save()
    return user


def _get_or_create_slack_user(slack_user_id, team_id, email=None, name=""):
    """
    Like _get_or_create_user, but for Slack installs where the bot doesn't
    have the users:read.email scope granted (email will be None) --
    matches by Slack identity instead so the user can still be recognized.
    """
    if email:
        return _get_or_create_user(email, name)

    user = User.objects(
        slack_account__slack_user_id=slack_user_id, slack_account__team_id=team_id
    ).first()
    if user is None:
        user = User(name=name)
        user.save()
    return user


# ---------------------------------------------------------------------------
# Slack OAuth
#
# This is the real "Add to Slack" install flow (OAuth v2), not the
# identity-only "Sign in with Slack". That distinction matters: identity-only
# sign-in can't be used by a brand new client, because it never actually
# installs the bot (with real permissions) into their workspace -- someone
# would still have to separately install it via the developer dashboard,
# which a real customer can't do. This flow installs the bot AND identifies
# the installing user in one step, so any workspace can self-serve onboard.
# ---------------------------------------------------------------------------

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_USERINFO_URL = "https://slack.com/api/users.info"


@require_GET
def slack_login(request):
    """
    Step 1: send the browser to Slack's "Add to Slack" consent screen.
    This is what the "Signup with Slack" button should link to.
    """
    state = secrets.token_urlsafe(24)
    request.session["slack_oauth_state"] = state

    # Carries the Organization Details filled in on the website signup
    # form through to slack_callback, once we know the real team_id.
    profile_token = request.GET.get("profile_token")
    if profile_token:
        request.session["pending_profile_token"] = profile_token

    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": settings.SLACK_BOT_SCOPES,
        "redirect_uri": settings.SLACK_REDIRECT_URI,
        "state": state,
    }
    return HttpResponseRedirect(f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}")


@require_GET
def slack_callback(request):
    """
    Step 2: Slack redirects here with ?code=...&state=...
    Exchanges the code for THIS WORKSPACE's own bot token, saves it
    (Workspace, keyed by team id -- never mixed with any other client's
    token), identifies the installing user with that new bot token, then
    bounces back to the frontend.
    """
    error = request.GET.get("error")
    if error:
        return _redirect_to_frontend(error=error)

    code = request.GET.get("code")
    state = request.GET.get("state")
    expected_state = request.session.pop("slack_oauth_state", None)
    if not code or not state or state != expected_state:
        return _redirect_to_frontend(error="invalid_state")

    token_resp = requests.post(
        SLACK_TOKEN_URL,
        data={
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.SLACK_REDIRECT_URI,
        },
        timeout=10,
    ).json()

    if not token_resp.get("ok"):
        return _redirect_to_frontend(error="slack_token_exchange_failed")

    bot_token = token_resp.get("access_token")
    bot_user_id = token_resp.get("bot_user_id", "")
    team = token_resp.get("team", {})
    team_id = team.get("id", "")
    authed_user_id = token_resp.get("authed_user", {}).get("id", "")

    if not bot_token or not team_id:
        return _redirect_to_frontend(error="slack_install_incomplete")

    existing_workspace = Workspace.objects(team_id=team_id).first()
    is_new_workspace = existing_workspace is None
    workspace = existing_workspace or Workspace(team_id=team_id)
    workspace.team_name = team.get("name", workspace.team_name)
    workspace.bot_token = bot_token
    workspace.bot_user_id = bot_user_id
    workspace.installed_by_slack_user_id = authed_user_id
    workspace.save()

    # Use the workspace's own brand-new bot token to look up who installed
    # it. `email` in the response requires the users:read.email bot scope --
    # if that scope isn't available/approved, profile.email will just be
    # absent and we identify the user by Slack identity instead (see
    # _get_or_create_slack_user).
    userinfo = requests.get(
        SLACK_USERINFO_URL,
        headers={"Authorization": f"Bearer {bot_token}"},
        params={"user": authed_user_id},
        timeout=10,
    ).json()
    profile = userinfo.get("user", {}).get("profile", {})
    display_name = profile.get("real_name") or userinfo.get("user", {}).get("name", "")

    email = profile.get("email")
    user = _get_or_create_slack_user(authed_user_id, team_id, email, display_name)
    user.name = user.name or display_name
    user.avatar_url = profile.get("image_192", user.avatar_url)
    user.slack_account = SlackAccount(
        slack_user_id=authed_user_id,
        team_id=team_id,
        team_name=team.get("name", ""),
        access_token=bot_token,
    )
    user.save()

    _log_user_in(request, user)

    if is_new_workspace:
        _attach_pending_org_profile(request, team_id)
        _finish_new_workspace_onboarding(team_id, authed_user_id, bot_token)

    # Existing workspace: nothing new to set up, straight into Slack.
    return HttpResponseRedirect(_slack_app_redirect_url(team_id))


def _attach_pending_org_profile(request, team_id: str) -> None:
    """
    If Organization Details was filled in on the website signup form
    before this Slack install, copy it into the real OrgProfile for this
    brand-new workspace and discard the pending copy. No-op if the
    installer skipped that form or came in through an existing workspace.
    """
    token = request.session.pop("pending_profile_token", None)
    if not token:
        return

    from cards.models_v2 import OrgProfile, PendingOrgProfile

    pending = PendingOrgProfile.objects(token=token).first()
    if pending is None:
        return

    profile = OrgProfile.objects(team_id=team_id).first() or OrgProfile(team_id=team_id)
    profile.org_name = pending.org_name
    profile.industry = pending.industry
    profile.website_url = pending.website_url
    profile.regions = list(pending.regions)
    profile.regulations = list(pending.regulations)
    profile.save()

    pending.delete()


def _finish_new_workspace_onboarding(team_id: str, authed_user_id: str, bot_token: str) -> None:
    """
    Creates the admin channel + the 3 participant channels, invites the
    installer into all of them, and posts the first cards.

    Guarded by claim_onboarding() so this can never run twice for the
    same workspace (confirmed live: a slow request plus a retry caused
    2-3 duplicate Welcome cards before this guard existed).
    """
    if not claim_onboarding(team_id):
        return
    send_new_design_preview(team_id, authed_user_id, bot_token)
    # NOTE: the cards posted below are still the hardcoded
    # "Sofia/ransomware" design-review content (cards/user_flow_test.py),
    # not a real personalized exercise -- sir asked to see the mockup
    # live in every new workspace for now, to be replaced with real
    # per-workspace data once the design is approved. #privacy-bridge
    # is deliberately left empty; it only opens once the participant
    # acknowledges Inject 3 in #ir-war-room.
    user_channels = ensure_user_channels(team_id, bot_token)
    war_room_id = user_channels.get("ir_war_room_channel_id")
    privacy_id = user_channels.get("privacy_bridge_channel_id")
    general_id = user_channels.get("general_channel_id")
    # Invite the installer into all 3 -- same as the admin channel
    # already does. Without this, they're created but invisible to
    # everyone (confirmed live: this exact gap on the first test).
    for channel_id in (war_room_id, privacy_id, general_id):
        if channel_id and authed_user_id:
            try:
                requests.post(
                    f"{SLACK_TOKEN_URL.rsplit('/', 1)[0]}/conversations.invite",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    data={"channel": channel_id, "users": authed_user_id},
                    timeout=10,
                )
            except requests.RequestException:
                pass
    if war_room_id:
        post_user_test_welcome(war_room_id, bot_token)
    if general_id:
        post_general_announcement(general_id, bot_token)


# ---------------------------------------------------------------------------
# Microsoft Teams (Azure AD) OAuth
# ---------------------------------------------------------------------------


def _teams_authorize_url():
    return (
        f"https://login.microsoftonline.com/{settings.TEAMS_TENANT_ID}"
        "/oauth2/v2.0/authorize"
    )


def _teams_token_url():
    return (
        f"https://login.microsoftonline.com/{settings.TEAMS_TENANT_ID}"
        "/oauth2/v2.0/token"
    )


TEAMS_USERINFO_URL = "https://graph.microsoft.com/oidc/userinfo"


@require_GET
def teams_login(request):
    """
    Step 1: send the browser to Microsoft's consent screen.
    This is what the "Signup with Teams" button should link to.
    """
    state = secrets.token_urlsafe(24)
    request.session["teams_oauth_state"] = state

    params = {
        "client_id": settings.TEAMS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.TEAMS_REDIRECT_URI,
        "response_mode": "query",
        "scope": settings.TEAMS_SCOPES,
        "state": state,
    }
    return HttpResponseRedirect(f"{_teams_authorize_url()}?{urlencode(params)}")


@require_GET
def teams_callback(request):
    """
    Step 2: Microsoft redirects here with ?code=...&state=...
    Exchange the code for a token, fetch the user's profile, create/update
    our User record, then bounce back to the frontend.
    """
    error = request.GET.get("error")
    if error:
        return _redirect_to_frontend(error=error)

    code = request.GET.get("code")
    state = request.GET.get("state")
    expected_state = request.session.pop("teams_oauth_state", None)
    if not code or not state or state != expected_state:
        return _redirect_to_frontend(error="invalid_state")

    token_resp = requests.post(
        _teams_token_url(),
        data={
            "client_id": settings.TEAMS_CLIENT_ID,
            "client_secret": settings.TEAMS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.TEAMS_REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": settings.TEAMS_SCOPES,
        },
        timeout=10,
    ).json()

    access_token = token_resp.get("access_token")
    if not access_token:
        return _redirect_to_frontend(error="teams_token_exchange_failed")

    userinfo = requests.get(
        TEAMS_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    ).json()

    email = userinfo.get("email") or userinfo.get("preferred_username")
    if not email:
        return _redirect_to_frontend(error="teams_email_missing")

    user = _get_or_create_user(email, userinfo.get("name", ""))
    user.name = user.name or userinfo.get("name", "")
    user.teams_account = TeamsAccount(
        aad_object_id=userinfo.get("sub", ""),
        tenant_id=userinfo.get("tid", settings.TEAMS_TENANT_ID),
        access_token=access_token,
        refresh_token=token_resp.get("refresh_token"),
    )
    user.save()

    _log_user_in(request, user)
    return _redirect_to_frontend()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _log_user_in(request, user: User):
    # mongoengine users aren't Django auth users, so we can't use
    # django.contrib.auth.login(). A plain session flag is enough here;
    # swap for a JWT/DRF token scheme later if the frontend needs one.
    request.session["user_id"] = str(user.id)
    request.session["user_email"] = user.email


def _slack_app_redirect_url(team_id: str) -> str:
    """
    Opens the Slack app itself (desktop client if installed, else
    slack.com in-browser) for this specific workspace, straight past the
    Slack post-install screen. Falls back to team.slack.com (still Slack,
    just not deep-linked to the app) if SLACK_APP_ID isn't configured.
    """
    if settings.SLACK_APP_ID:
        return f"https://slack.com/app_redirect?app={settings.SLACK_APP_ID}&team={team_id}"
    return "https://slack.com/"


def _redirect_to_frontend(error: str | None = None):
    path = settings.FRONTEND_LOGIN_ERROR_PATH if error else settings.FRONTEND_LOGIN_SUCCESS_PATH
    url = f"{settings.FRONTEND_URL}{path}"
    if error:
        url += f"?error={error}"
    return HttpResponseRedirect(url)


@api_view(["GET"])
def me(request):
    """Simple endpoint the frontend can call to check who's logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        return Response({"authenticated": False}, status=200)

    user = User.objects(id=user_id).first()
    if not user:
        return Response({"authenticated": False}, status=200)

    return Response(
        {
            "authenticated": True,
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "has_slack": bool(user.slack_account),
            "has_teams": bool(user.teams_account),
        }
    )
