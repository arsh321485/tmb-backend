"""
The actual logic behind each /testmyplan subcommand.

These return plain dicts shaped like Slack's "message" response format
(https://api.slack.com/interactivity/slash-commands#responding_immediate_response).
They're stubbed with placeholder data for now -- the real Exercise/Drill
models (from the tracker's "Exercise orchestration" domain) aren't built
yet, so wire these up to real queries once those exist.
"""

SUPPORTED_SUBCOMMANDS = ["run", "status", "gaps", "plans", "pause", "abort"]


def _ephemeral(text):
    """Only the person who typed the command sees this."""
    return {"response_type": "ephemeral", "text": text}


def handle_run(args, user_id):
    # TODO: look up the requested scenario, provision the exercise channel,
    # start the exercise state machine (Exercise orchestration domain, D1-D14).
    scenario = args or "a default scenario"
    return _ephemeral(
        f":rocket: Starting exercise *{scenario}*... "
        "(this will provision a channel and invite participants once "
        "exercise orchestration is built)."
    )


def handle_status(args, user_id):
    # TODO: query the active Exercise for this workspace/user and report
    # real progress instead of this placeholder.
    return _ephemeral(
        "*No exercise currently running.* Once exercises are wired up, "
        "this will show the live status of anything in progress."
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
    # TODO: pause the active exercise (D7 in-chat facilitator console).
    return _ephemeral("*No running exercise to pause.*")


def handle_abort(args, user_id):
    # TODO: abort + stand-down (D14).
    return _ephemeral("*No running exercise to abort.*")


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
