"""
The actual logic behind each /testmyplan subcommand.

These return plain dicts shaped like Slack's "message" response format
(https://api.slack.com/interactivity/slash-commands#responding_immediate_response).

`run`, `status`, `pause` and `abort` are wired to a real Exercise record and
a real auto-provisioned Slack channel (A6). `gaps` and `plans` are still
stubbed -- they depend on the Plan intake & intelligence domain (B1-B9),
which isn't built yet.
"""

from exercises.models import (
    STATUS_ABORTED,
    STATUS_COMPLETED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    Exercise,
)
from exercises.slack_channels import SlackApiError, archive_exercise_channel, provision_exercise_channel

SUPPORTED_SUBCOMMANDS = ["run", "status", "gaps", "plans", "pause", "abort"]


def _ephemeral(text):
    """Only the person who typed the command sees this."""
    return {"response_type": "ephemeral", "text": text}


def _active_exercise_for(user_id):
    return Exercise.objects(
        started_by_slack_user_id=user_id, status__in=[STATUS_RUNNING, STATUS_PAUSED]
    ).first()


def handle_run(args, user_id):
    if _active_exercise_for(user_id):
        return _ephemeral(
            "*You already have an exercise running.* Use `/testmyplan status` "
            "to check it or `/testmyplan abort` to end it first."
        )

    scenario = args or "Unnamed scenario"
    exercise = Exercise(scenario_name=scenario, started_by_slack_user_id=user_id)

    try:
        channel = provision_exercise_channel(scenario, user_id)
    except SlackApiError as exc:
        return _ephemeral(
            f":warning: Couldn't create the exercise channel ({exc}). "
            "Check the bot has the `channels:manage` and `chat:write` scopes."
        )

    exercise.slack_channel_id = channel["id"]
    exercise.slack_channel_name = channel["name"]
    exercise.save()

    return _ephemeral(
        f":rocket: Started exercise *{scenario}* in <#{channel['id']}|{channel['name']}>."
    )


def handle_status(args, user_id):
    exercise = _active_exercise_for(user_id)
    if exercise is None:
        return _ephemeral("*No exercise currently running.*")

    channel_ref = (
        f"<#{exercise.slack_channel_id}|{exercise.slack_channel_name}>"
        if exercise.slack_channel_id
        else "(no channel)"
    )
    return _ephemeral(
        f"*{exercise.scenario_name}* -- status: `{exercise.status}` -- {channel_ref}"
    )


def handle_gaps(args, user_id):
    # TODO: pull from the Plan gap review feature (B4) once plan parsing exists.
    return _ephemeral(
        "*Plan gap review isn't wired up yet.* This will list undefined "
        "owners, missing escalation criteria and conflicting recovery "
        "targets once plan intake is built."
    )


def handle_plans(args, user_id):
    # TODO: list uploaded plans and their versions (B1, B8).
    return _ephemeral(
        "*No plans uploaded yet.* Drop a DOCX/PDF/XLSX plan into a DM with "
        "the app once plan intake is built, and it'll show up here."
    )


def handle_pause(args, user_id):
    exercise = _active_exercise_for(user_id)
    if exercise is None:
        return _ephemeral("*No running exercise to pause.*")

    exercise.status = STATUS_PAUSED
    exercise.save()
    return _ephemeral(f"*{exercise.scenario_name}* paused.")


def handle_abort(args, user_id):
    exercise = _active_exercise_for(user_id)
    if exercise is None:
        return _ephemeral("*No running exercise to abort.*")

    if exercise.slack_channel_id:
        try:
            archive_exercise_channel(exercise.slack_channel_id)
        except SlackApiError:
            pass  # still mark it aborted even if archiving the channel failed

    exercise.status = STATUS_ABORTED
    exercise.save()
    return _ephemeral(f":octagonal_sign: *{exercise.scenario_name}* aborted and stood down.")


_HANDLERS = {
    "run": handle_run,
    "status": handle_status,
    "gaps": handle_gaps,
    "plans": handle_plans,
    "pause": handle_pause,
    "abort": handle_abort,
}


def dispatch(command_text: str, user_id: str) -> dict:
    """
    command_text is whatever came after `/testmyplan`, e.g. "run ransomware".
    Returns a Slack message dict to send back as the response.
    """
    command_text = (command_text or "").strip()
    subcommand, _, args = command_text.partition(" ")
    subcommand = subcommand.lower()

    handler = _HANDLERS.get(subcommand)
    if handler is None:
        return _ephemeral(
            f"Unknown command `{subcommand or '(none)'}`. Try one of: "
            + ", ".join(f"`{c}`" for c in SUPPORTED_SUBCOMMANDS)
        )

    return handler(args.strip(), user_id)
