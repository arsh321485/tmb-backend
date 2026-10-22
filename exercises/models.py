import datetime

import mongoengine as me

STATUS_SCHEDULED = "scheduled"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_ABORTED = "aborted"

STATUS_CHOICES = (STATUS_SCHEDULED, STATUS_RUNNING, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ABORTED)


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

    # When module actually carries a real plan_id (e.g. "RW-01") -- sir's
    # call: trigger one Phase of the plan at a time instead of always
    # running the whole plan end to end. The live inject chain starts at
    # this phase's first inject and stops once it would cross into the
    # next phase, rather than always starting at the plan's very first
    # inject.
    inject_phase = me.StringField(required=False)
    status = me.StringField(choices=STATUS_CHOICES, default=STATUS_RUNNING)

    started_by_slack_user_id = me.StringField(required=False)
    slack_team_id = me.StringField(required=False)
    slack_channel_id = me.StringField(required=False)
    slack_channel_name = me.StringField(required=False)

    # "Schedule" trigger -- when the drill should actually fire. Set at
    # creation (picked in a modal), checked by a recurring background job
    # (exercises/apps.py) that fires it once this time arrives, same
    # pattern as backup escalation. Unset for "now"/"surprise" exercises,
    # which fire immediately and are never "scheduled" status.
    scheduled_at = me.DateTimeField(required=False)
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
TASK_STATUS_ABORTED = "aborted"  # drill stopped manually before this task was resolved

TASK_STATUS_CHOICES = (TASK_STATUS_SENT, TASK_STATUS_DONE, TASK_STATUS_ESCALATED, TASK_STATUS_ABORTED)


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

    # Had this person actually clicked "I acknowledge" on the real
    # Welcome -> Role -> Acknowledge DM flow (role_welcome_v2.py) BEFORE
    # this drill paged them? Recorded at send time from the TeamMember's
    # acknowledged_by, so the report can show who was genuinely briefed
    # versus who heard about their role for the first time mid-drill.
    was_acknowledged = me.BooleanField(default=False)

    status = me.StringField(choices=TASK_STATUS_CHOICES, default=TASK_STATUS_SENT)
    sent_at = me.DateTimeField(default=datetime.datetime.utcnow)
    responded_at = me.DateTimeField(required=False)
    response_text = me.StringField(required=False)  # what they typed/picked when marking done, if anything

    meta = {"collection": "exercise_tasks", "ordering": ["sent_at"], "strict": False}


class DecisionResponse(me.Document):
    """
    One real answer to one real inject's decision question (sir's
    TMP_Ransomware_Injects.xlsx -- Injects + Decision Options sheets).
    The participant only ever sees the feedback text for their chosen
    option, never score/rating -- those are admin-only, read from here
    for the live board / report / debrief.
    """

    exercise = me.ReferenceField(Exercise, required=True)
    inject_id = me.StringField(required=True)  # catalog id, e.g. "RW01-TRIG"
    decision_id = me.StringField(required=True)
    assigned_slack_user_id = me.StringField(required=True)
    team_name = me.StringField(required=False)
    role = me.StringField(required=False)

    chosen_option = me.StringField(required=False)  # "A"/"B"/"C"/"D", unset until answered
    score = me.IntField(required=False)
    rating = me.StringField(required=False)  # Best / Acceptable / Partial / Poor
    triggered_inject_id = me.StringField(required=False)  # the consequence inject this answer chained into, if any

    # The real response timer from the spreadsheet -- due_at is the real
    # deadline (sent_at + Response Timer (min)), shown to the participant
    # as an actual clock time. escalated guards against re-processing the
    # same overdue decision twice on the next background check; is_backup
    # marks a decision that was re-sent to the backup after the primary
    # timed out.
    due_at = me.DateTimeField(required=False)
    escalated = me.BooleanField(default=False)
    is_backup = me.BooleanField(default=False)
    timed_out = me.BooleanField(default=False)  # auto-resolved with no real answer -- primary AND backup both missed it

    # The real plan-sequence position to resume the Main sequence from
    # once any chain of Consequence injects stemming from this one is
    # done -- Consequence injects have no seq of their own, so without
    # this the chain has no way back to the next real Main inject
    # (e.g. Declare Incident) after a poor choice's detour.
    resume_seq = me.IntField(required=False)

    # The DM itself -- needed to edit it in place (chat.update) once they
    # answer, showing feedback instead of the still-open option buttons.
    slack_channel_id = me.StringField(required=False)
    slack_message_ts = me.StringField(required=False)

    sent_at = me.DateTimeField(default=datetime.datetime.utcnow)
    responded_at = me.DateTimeField(required=False)

    meta = {"collection": "decision_responses", "ordering": ["sent_at"], "strict": False}
