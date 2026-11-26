"""
Real persistence for the Scenario-review-on-website OTP flow (mirrors
teams_portal/models.py's TeamsPortalOtp) -- a short-lived login-code step
in front of cards/models_v2.py's real GeneratedScenario, scoped to the
one scenario a Slack user clicked "View on website" for.
"""

import datetime

import mongoengine as me


class ScenarioPortalOtp(me.Document):
    """
    One real one-time code, DMed to the real Slack user who clicked
    "View on website" on a scenario review card (cards/interactivity_v2.py's
    v2_scenario_open_portal handler) -- team_id/slack_user_id/scenario_id
    come from that click, never from anything the website itself claims.
    """

    team_id = me.StringField(required=True)
    slack_user_id = me.StringField(required=True)
    scenario_id = me.StringField(required=True)
    channel_id = me.StringField(required=False)
    code_hash = me.StringField(required=True)
    expires_at = me.DateTimeField(required=True)
    attempts = me.IntField(default=0)
    verified = me.BooleanField(default=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "scenario_portal_otps", "strict": False}
