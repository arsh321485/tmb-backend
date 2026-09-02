import datetime

import mongoengine as me

STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_ABORTED = "aborted"

STATUS_CHOICES = (STATUS_RUNNING, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ABORTED)


class Exercise(me.Document):
    """
    One run of a drill/exercise (Exercise orchestration domain, D1-D14).
    For now this only tracks enough to support auto-provisioned channels
    (A6): who started it, which scenario, and which Slack channel was
    created for it. Timed injects, decision cards, scoring etc. are for
    later once the rest of that domain is built.
    """

    scenario_name = me.StringField(required=True)
    status = me.StringField(choices=STATUS_CHOICES, default=STATUS_RUNNING)

    started_by_slack_user_id = me.StringField(required=False)
    slack_team_id = me.StringField(required=False)
    slack_channel_id = me.StringField(required=False)
    slack_channel_name = me.StringField(required=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)
    ended_at = me.DateTimeField(required=False)

    meta = {"collection": "exercises", "ordering": ["-created_at"]}
