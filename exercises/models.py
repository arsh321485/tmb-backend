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
    module = me.StringField(required=False)  # "Cybersecurity" or "Privacy" -- which war-room-type channel this runs in
    trigger_type = me.StringField(required=False)  # "now" / "sched" / "surprise"
    status = me.StringField(choices=STATUS_CHOICES, default=STATUS_RUNNING)

    started_by_slack_user_id = me.StringField(required=False)
    slack_team_id = me.StringField(required=False)
    slack_channel_id = me.StringField(required=False)
    slack_channel_name = me.StringField(required=False)
    # A7: people invited into THIS exercise's channel specifically (e.g. a
    # vendor, an exec) -- separate from the standing admin/response teams.
    external_participant_ids = me.ListField(me.StringField(), default=list)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)
    ended_at = me.DateTimeField(required=False)

    # strict=False: tolerate old field names left over in already-saved
    # documents from a since-reverted schema change (a "trigger_type"
    # field existed briefly during testing) -- same fix as WizardState's
    # for the same underlying issue.
    meta = {"collection": "exercises", "ordering": ["-created_at"], "strict": False}


TASK_STATUS_SENT = "sent"
TASK_STATUS_DONE = "done"
TASK_STATUS_ESCALATED = "escalated"  # primary timed out, backup was DM'd instead

TASK_STATUS_CHOICES = (TASK_STATUS_SENT, TASK_STATUS_DONE, TASK_STATUS_ESCALATED)


class ExerciseTask(me.Document):
    """
    Step 3/4 of Trigger -- one row per real person DM'd their job when a
    drill fires (from the real Team/TeamMember data set in Card 4). The
    stopwatch we've been describing: sent_at when their DM goes out,
    responded_at when they click Done, which becomes the real response
    time the report is built from.
    """

    exercise = me.ReferenceField(Exercise, required=True)
    team_name = me.StringField(required=True)
    role = me.StringField(required=True)

    assigned_slack_user_id = me.StringField(required=True)  # whoever actually got DM'd -- primary, or backup after escalation
    is_backup = me.BooleanField(default=False)  # true once escalated to the backup
    primary_slack_user_id = me.StringField(required=False)
    backup_slack_user_id = me.StringField(required=False)

    responsibility_text = me.StringField(required=False)
    action = me.StringField(required=False)
    detail = me.StringField(required=False)
    phase = me.StringField(required=False)

    status = me.StringField(choices=TASK_STATUS_CHOICES, default=TASK_STATUS_SENT)
    sent_at = me.DateTimeField(default=datetime.datetime.utcnow)
    responded_at = me.DateTimeField(required=False)
    response_text = me.StringField(required=False)  # what they typed/picked when marking done, if anything

    meta = {"collection": "exercise_tasks", "ordering": ["sent_at"], "strict": False}
