"""
Verifies that an incoming request really came from Slack.

Slack signs every request with your app's Signing Secret. We recompute the
same signature and compare it to the one Slack sent us; if they don't match,
the request is rejected. See: https://api.slack.com/authentication/verifying-requests-from-slack
"""

import hashlib
import hmac
import time

from django.conf import settings


class SlackSignatureError(Exception):
    pass


def verify_slack_signature(request):
    """
    Raises SlackSignatureError if the request isn't a genuine Slack request.
    No-ops (does nothing) if SLACK_SIGNING_SECRET isn't configured yet, so
    local development works before that secret is set.
    """
    if not settings.SLACK_SIGNING_SECRET:
        return

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    slack_signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp or not slack_signature:
        raise SlackSignatureError("Missing Slack signature headers")

    # Reject requests older than 5 minutes, to stop replay attacks.
    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise SlackSignatureError("Request timestamp too old")

    sig_basestring = f"v0:{timestamp}:{request.body.decode('utf-8')}"
    computed_signature = "v0=" + hmac.new(
        settings.SLACK_SIGNING_SECRET.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, slack_signature):
        raise SlackSignatureError("Invalid Slack signature")
