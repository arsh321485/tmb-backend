import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import SlackAccount, TeamsAccount, User

# ---------------------------------------------------------------------------
# Slack OAuth
# ---------------------------------------------------------------------------

SLACK_AUTHORIZE_URL = "https://slack.com/openid/connect/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/openid.connect.token"
SLACK_USERINFO_URL = "https://slack.com/api/openid.connect.userInfo"


@require_GET
def slack_login(request):
    """
    Step 1: send the browser to Slack's consent screen.
    This is what the "Signup with Slack" button should link to.
    """
    state = secrets.token_urlsafe(24)
    request.session["slack_oauth_state"] = state

    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": settings.SLACK_SCOPES,
        "redirect_uri": settings.SLACK_REDIRECT_URI,
        "state": state,
        "response_type": "code",
    }
    return HttpResponseRedirect(f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}")


@require_GET
def slack_callback(request):
    """
    Step 2: Slack redirects here with ?code=...&state=...
    Exchange the code for a token, fetch the user's profile, create/update
    our User record, then bounce back to the frontend.
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

    if not token_resp.get("ok", True) and "access_token" not in token_resp:
        return _redirect_to_frontend(error="slack_token_exchange_failed")

    access_token = token_resp.get("access_token")

    userinfo = requests.get(
        SLACK_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    ).json()

    email = userinfo.get("email")
    if not email:
        return _redirect_to_frontend(error="slack_email_missing")

    user, _created = User.objects.get_or_create(
        email=email, defaults={"name": userinfo.get("name", "")}
    )
    user.name = user.name or userinfo.get("name", "")
    user.avatar_url = userinfo.get("picture", user.avatar_url)
    user.slack_account = SlackAccount(
        slack_user_id=userinfo.get("sub", ""),
        team_id=userinfo.get("https://slack.com/team_id", ""),
        team_name=userinfo.get("https://slack.com/team_name", ""),
        access_token=access_token,
    )
    user.save()

    _log_user_in(request, user)
    return _redirect_to_frontend()


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

    user, _created = User.objects.get_or_create(
        email=email, defaults={"name": userinfo.get("name", "")}
    )
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
