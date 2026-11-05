"""
Step 3/4/5 of Trigger -- the real "DM everyone their job, start the
stopwatch, escalate to backup if they don't answer" part. Uses the real
Team/TeamMember data already saved from Card 4 (Teams); previously
nothing was ever sent when a drill started.
"""

import datetime
import logging

from cards.slack_client import SlackApiError, _call

from .models import STATUS_RUNNING, Exercise, ExerciseTask

logger = logging.getLogger(__name__)

# Step 5 -- how long a primary gets before their backup is pulled in.
# Short on purpose for a click-through drill (real incidents move fast);
# tune this once sir has an opinion on the real SLA per role/phase.
ESCALATE_AFTER_MINUTES = 5


def _name(by_code: dict, slack_user_id: str) -> str:
    return by_code.get(slack_user_id, {}).get("n", slack_user_id) if slack_user_id else ""


def send_drill_tasks(exercise: Exercise, bot_token: str, by_code: dict) -> list:
    """
    DMs every real staffed team member (across every team in the
    workspace, any tier) their job for this drill, and saves one
    ExerciseTask per person so responses can be tracked. Returns the
    created tasks.
    """
    from cards.models_v2 import Team, TeamMember

    tasks = []
    for team_doc in Team.objects(team_id=exercise.slack_team_id):
        for tm in TeamMember.objects(team=team_doc):
            primary_id = tm.primary_slack_user_ids[0] if tm.primary_slack_user_ids else ""
            backup_id = tm.backup_slack_user_ids[0] if tm.backup_slack_user_ids else ""
            if not primary_id:
                continue  # role listed but nobody actually assigned yet

            mapped = tm.mapped_responsibilities[0] if tm.mapped_responsibilities else {}
            task = ExerciseTask(
                exercise=exercise,
                team_name=team_doc.name,
                role=tm.role,
                assigned_slack_user_id=primary_id,
                is_backup=False,
                primary_slack_user_id=primary_id,
                backup_slack_user_id=backup_id,
                responsibility_text=mapped.get("responsibility", ""),
                action=mapped.get("action", ""),
                detail=mapped.get("detail", ""),
                phase=mapped.get("phase", ""),
                was_acknowledged=primary_id in (tm.acknowledged_by or {}),
            )
            task.save()
            tasks.append(task)

            try:
                _send_task_dm(task, bot_token)
            except SlackApiError:
                logger.exception("Failed to DM drill task %s to %s", task.id, primary_id)

    return tasks


def _send_task_dm(task: ExerciseTask, bot_token: str, is_backup: bool = False) -> None:
    opened = _call("conversations.open", bot_token, users=task.assigned_slack_user_id)
    dm_channel_id = opened["channel"]["id"]

    headline = ":arrows_counterclockwise: The primary didn't respond in time — you're up" if is_backup else ":fire: A drill just started"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": headline, "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Team*\n{task.team_name}"},
                {"type": "mrkdwn", "text": f"*Your role*\n{task.role}"},
            ],
        },
    ]
    if not task.was_acknowledged:
        # They're being paged for a role they never confirmed being ready
        # for (no real "I acknowledge" on file) -- still sent, since
        # skipping them would leave the role uncovered during a drill,
        # but flagged so it's visible to them and in the report.
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":warning: You haven't acknowledged this role yet — this is your first time hearing about it."}],
            }
        )
    if task.responsibility_text:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Responsibility*\n{task.responsibility_text}"},
                    {"type": "mrkdwn", "text": f"*Action*\n{task.action}: {task.detail}"},
                    {"type": "mrkdwn", "text": f"*Test phase*\n{task.phase}"},
                ],
            }
        )
    blocks.append(
        {
            "type": "actions",
            "block_id": f"drilltask|{task.id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Done", "emoji": True},
                    "action_id": "v2_drill_task_done",
                    "value": str(task.id),
                    "style": "primary",
                }
            ],
        }
    )
    backup_note = "" if is_backup else f" If you haven't clicked Done within {ESCALATE_AFTER_MINUTES} minutes, your backup will be notified instead."
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"This is a readiness drill, not a real incident. Click Done once you've completed the action above.{backup_note}"}],
        }
    )

    _call(
        "chat.postMessage",
        bot_token,
        channel=dm_channel_id,
        text=f"Drill started — your job: {task.role} on {task.team_name}",
        blocks=blocks,
    )


def fire_exercise(exercise: Exercise, bot_token: str) -> None:
    """
    The real "go live" moment -- posts the war-room alarm and DMs every
    real staffed team member their job. Shared by the immediate paths
    ("now"/"surprise", fired straight from the click) and by
    fire_due_scheduled_exercises below ("sched", fired later by the
    background check once its scheduled_at arrives) so there's exactly
    one place that does the actual firing.
    """
    from cards.trigger_v2_data import TRIGGER_LABELS

    if exercise.slack_channel_id and bot_token:
        alarm_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: Incident detected", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{exercise.scenario_name}*"}},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{TRIGGER_LABELS.get(exercise.trigger_type, exercise.trigger_type)} · this is a TestMyPlan readiness drill — do not action externally.",
                    }
                ],
            },
        ]
        _call(
            "chat.postMessage",
            bot_token,
            channel=exercise.slack_channel_id,
            text=f"Incident detected — {exercise.scenario_name}",
            blocks=alarm_blocks,
        )

    # Generic "Click Done" readiness task DMs removed here (sir's call)
    # -- only the real decision cards below should go out once a drill
    # starts, not a separate readiness-check card per person first.
    # send_drill_tasks/_send_task_dm are left in place, just unused from
    # here, in case sir wants them back for a plan with no real injects.

    # Real injects + scored decisions (sir's TMP_Ransomware_Injects.xlsx)
    # -- only for a drill reached through the real-plan path, where
    # exercise.module carries the real plan_id (e.g. "RW-01") instead of
    # a generic "Cybersecurity"/"Privacy" module name. Starts the real
    # inject sequence at seq 1; each answered decision releases the next
    # one (cards/inject_drill_v2.py).
    if bot_token:
        from cards.inject_catalog_v2 import injects_for_plan
        from cards.inject_drill_v2 import send_inject

        sequence = injects_for_plan(exercise.module)
        if exercise.inject_phase:
            # Phase-scoped trigger -- start at that phase's own first
            # inject instead of always the whole plan's first one.
            sequence = [i for i in sequence if i["phase"] == exercise.inject_phase]
        if sequence:
            send_inject(exercise, sequence[0], bot_token)


def fire_due_scheduled_exercises() -> int:
    """
    Finds every "scheduled" exercise whose scheduled_at has arrived, fires
    it for real, and flips it to "running". Meant to be called on a
    recurring timer (see exercises/apps.py), same pattern as
    escalate_overdue_tasks.
    """
    from workspaces.models import get_bot_token

    due = Exercise.objects(status="scheduled", scheduled_at__lte=datetime.datetime.utcnow())

    count = 0
    for exercise in due:
        bot_token = get_bot_token(exercise.slack_team_id)
        if not bot_token:
            continue
        try:
            fire_exercise(exercise, bot_token)
        except SlackApiError:
            logger.exception("Failed to fire scheduled exercise %s", exercise.id)
            continue
        exercise.status = STATUS_RUNNING
        exercise.save()
        count += 1

    return count


def escalate_overdue_tasks() -> int:
    """
    Step 5 -- finds every task still "sent" (nobody clicked Done) past
    ESCALATE_AFTER_MINUTES, marks it escalated, and DMs the backup person
    the exact same job. Returns how many were escalated. Meant to be
    called on a recurring timer (see exercises/apps.py).
    """
    from workspaces.models import get_bot_token

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=ESCALATE_AFTER_MINUTES)
    # backup_slack_user_id can be unset (None) or "" depending on how the
    # task was created -- filtered properly inside the loop below instead
    # of trying to express both "empty" cases in one Mongo query.
    overdue = ExerciseTask.objects(status="sent", sent_at__lt=cutoff)

    count = 0
    for task in overdue:
        if not task.backup_slack_user_id:
            continue

        task.status = "escalated"
        task.save()

        exercise = task.exercise
        bot_token = get_bot_token(exercise.slack_team_id) if exercise else None
        if not bot_token:
            continue

        from cards.models_v2 import Team, TeamMember

        was_acknowledged = False
        team_doc = Team.objects(team_id=exercise.slack_team_id, name=task.team_name).first()
        tm = TeamMember.objects(team=team_doc, role=task.role).first() if team_doc else None
        if tm:
            was_acknowledged = task.backup_slack_user_id in (tm.acknowledged_by or {})

        backup_task = ExerciseTask(
            exercise=exercise,
            team_name=task.team_name,
            role=task.role,
            assigned_slack_user_id=task.backup_slack_user_id,
            is_backup=True,
            primary_slack_user_id=task.primary_slack_user_id,
            backup_slack_user_id=task.backup_slack_user_id,
            was_acknowledged=was_acknowledged,
            responsibility_text=task.responsibility_text,
            action=task.action,
            detail=task.detail,
            phase=task.phase,
        )
        backup_task.save()

        try:
            _send_task_dm(backup_task, bot_token, is_backup=True)
        except SlackApiError:
            logger.exception("Failed to DM backup for overdue drill task %s", task.id)

        count += 1

    return count
