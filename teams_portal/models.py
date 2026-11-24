"""
Real persistence for the Teams-on-website OTP flow (cards/models_v2.py's
Team/TeamMember are the actual team data; this is just the short-lived
login-code step in front of it). Kept as its own small app/collection
instead of folding into cards/models_v2.py since this is a
website-portal-auth concern, not a Slack-card concern.
"""

import datetime

import mongoengine as me


class TeamsPortalOtp(me.Document):
    """
    One real one-time code, DMed to the real Slack user who clicked
    "Assign on website" -- team_id + slack_user_id come from that click
    (cards/interactivity_v2.py's v2_teams_open_portal handler), never
    from anything the website itself claims. code_hash so a DB read
    alone can't leak the real code; attempts caps brute-forcing it.
    """

    team_id = me.StringField(required=True)
    slack_user_id = me.StringField(required=True)
    code_hash = me.StringField(required=True)
    expires_at = me.DateTimeField(required=True)
    attempts = me.IntField(default=0)
    verified = me.BooleanField(default=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "teams_portal_otps", "strict": False}
