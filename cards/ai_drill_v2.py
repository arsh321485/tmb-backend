"""
A23/A24 -- runs an APPROVED GeneratedScenario (plans/scenario_generator.py)
as a real live drill: sends real DMs to real people, real decision
buttons, real scored answers, real consequence chaining.

Deliberately its own file, touching nothing in cards/inject_catalog_v2.py,
cards/plan_catalog_v2.py or exercises/drill.py -- those run the 3
pre-built drills (RW-01/02/03) and are left exactly as they are. This
file only reuses stable, generic building blocks (the Slack API client,
and reading -- never writing -- Team/TeamMember) to avoid any risk of
breaking what already works.
"""

import logging

from .models_v2 import AIDecisionResponse, AIExerciseRun, GeneratedScenario, RUN_STATUS_COMPLETED, RUN_STATUS_RUNNING, RUN_STATUS_SCHEDULED
from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)


def _resolve_recipient(team_id: str, role: str) -> str | None:
    """The real Slack user id currently primary for this exact role name,
    in this workspace -- read-only lookup against Team/TeamMember, same
    data Teams & Roles already manages."""
    from .models_v2 import Team, TeamMember

    for team_doc in Team.objects(team_id=team_id):
        tm = TeamMember.objects(team=team_doc, role=role).first()
        if tm and tm.primary_slack_user_ids:
            return tm.primary_slack_user_ids[0]
    return None


def build_trigger_picker_card(scenario: GeneratedScenario) -> dict:
    """First real step after Approve (flowchart's "Training mode?" box):
    Yes sends everyone a real pre-notification DM before anything else
    happens; No skips straight to the Trigger/Schedule/Surprise picker,
    same as the drill always worked before this existed."""
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":white_check_mark: Approved -- ready to run", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Training mode? (sends a heads-up DM to everyone involved before the test starts)"}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes -- send pre-notification", "emoji": True}, "action_id": "v2_ai_training_yes", "value": str(scenario.id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No -- send test directly", "emoji": True}, "action_id": "v2_ai_training_no", "value": str(scenario.id)},
                ],
            },
        ]
    }


def build_timing_picker_card(scenario: GeneratedScenario, training_mode: bool) -> dict:
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    mode_note = ":white_check_mark: Pre-notification sent." if training_mode else "Sending directly -- no advance warning."
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":dart: Choose when to run", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_  ·  {mode_note}"}]},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Choose when to run this scenario for real."}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Trigger now", "emoji": True}, "action_id": "v2_ai_trigger_now", "value": f"{scenario.id}|{int(training_mode)}", "style": "danger"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Schedule", "emoji": True}, "action_id": "v2_ai_trigger_schedule_open", "value": f"{scenario.id}|{int(training_mode)}"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Surprise window", "emoji": True}, "action_id": "v2_ai_trigger_surprise", "value": f"{scenario.id}|{int(training_mode)}"},
                ],
            },
        ]
    }


def send_pre_notification(scenario: GeneratedScenario, bot_token: str) -> int:
    """Training mode = Yes: a real heads-up DM to every real person who
    holds a role targeted anywhere in this scenario, before anything
    else fires. Returns how many people were actually reached."""
    roles = {inj.get("target_role", "") for inj in scenario.injects if inj.get("target_role")}
    breadcrumb = f"{scenario.threat_label} › {scenario.incident_name} › {scenario.cause_name}"
    sent_to = set()
    for role in roles:
        recipient = _resolve_recipient(scenario.team_id, role)
        if not recipient or recipient in sent_to:
            continue
        try:
            opened = _call("conversations.open", bot_token, users=recipient)
            dm_channel_id = opened["channel"]["id"]
            _call(
                "chat.postMessage", bot_token, channel=dm_channel_id,
                text=f":bell: Heads up -- a TestMyPlan drill ({breadcrumb}) involving your role ({role}) will run soon.",
            )
            sent_to.add(recipient)
        except SlackApiError:
            logger.exception("AI scenario %s: failed to send pre-notification to %s", scenario.id, recipient)
    return len(sent_to)


def build_run_status_card(run: AIExerciseRun, scenario: GeneratedScenario) -> dict:
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    if run.status == RUN_STATUS_SCHEDULED:
        text = f":alarm_clock: Scheduled for {run.scheduled_at.strftime('%d %b %Y, %H:%M UTC')}."
    elif run.status == RUN_STATUS_RUNNING:
        text = ":rotating_light: Live -- injects are going out to real people now."
    else:
        text = ":checkered_flag: Completed."
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":dart: AI scenario run", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]
    }


def start_run(
    scenario: GeneratedScenario, trigger_type: str, started_by: str, bot_token: str, scheduled_at=None,
    origin_channel_id: str = "", training_mode: bool = False,
) -> AIExerciseRun:
    import datetime

    run = AIExerciseRun(
        team_id=scenario.team_id, scenario=scenario, trigger_type=trigger_type,
        started_by_slack_user_id=started_by, origin_channel_id=origin_channel_id,
        training_mode=training_mode,
        status=RUN_STATUS_SCHEDULED if scheduled_at else RUN_STATUS_RUNNING,
        scheduled_at=scheduled_at,
        started_at=None if scheduled_at else datetime.datetime.utcnow(),
    )
    run.save()
    if not scheduled_at:
        _fire_next_inject(run, bot_token)
    return run


def check_scheduled_ai_runs() -> int:
    """Called from the same recurring background check as everything
    else (exercises/apps.py) -- fires any AI run whose scheduled time
    has arrived. Only ever touches AIExerciseRun, never the real
    Exercise collection."""
    import datetime

    from workspaces.models import get_bot_token

    fired = 0
    due = AIExerciseRun.objects(status=RUN_STATUS_SCHEDULED, scheduled_at__lte=datetime.datetime.utcnow())
    for run in due:
        bot_token = get_bot_token(run.team_id)
        if not bot_token:
            continue
        run.status = RUN_STATUS_RUNNING
        run.started_at = datetime.datetime.utcnow()
        run.save()
        _fire_next_inject(run, bot_token)
        fired += 1
    return fired


def _find_inject(scenario: GeneratedScenario, *, seq: int | None = None, inject_id: str | None = None) -> dict | None:
    for inj in scenario.injects:
        if seq is not None and inj.get("seq") == seq:
            return inj
        if inject_id is not None and inj.get("inject_id") == inject_id:
            return inj
    for inj in scenario.consequence_injects:
        if inject_id is not None and inj.get("inject_id") == inject_id:
            return inj
    return None


def _fire_next_inject(run: AIExerciseRun, bot_token: str) -> None:
    scenario = run.scenario
    main_injects = sorted(scenario.injects, key=lambda i: i.get("seq", 0))
    next_inject = None
    for inj in main_injects:
        if run.current_seq is None or inj.get("seq", 0) > run.current_seq:
            next_inject = inj
            break

    if not next_inject:
        run.status = RUN_STATUS_COMPLETED
        import datetime

        run.ended_at = datetime.datetime.utcnow()
        run.save()
        _post_report(run, bot_token)
        return

    run.current_seq = next_inject.get("seq")
    run.save()
    _send_inject_dm(run, next_inject, bot_token)


def build_report_card(run: AIExerciseRun) -> dict:
    scenario = run.scenario
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    responses = list(AIDecisionResponse.objects(run=run).order_by("sent_at"))

    scored = [r for r in responses if r.score is not None]
    total_score = sum(r.score for r in scored)
    max_possible = sum(10 for _ in scored)  # every option set is scored out of 10 in the real options list

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":checkered_flag: Drill report", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Total score: {total_score} / {max_possible}*" if scored else "_No decisions were answered._"}},
        {"type": "divider"},
    ]

    for r in responses:
        inject = _find_inject(scenario, inject_id=r.inject_id)
        title = inject.get("title", r.inject_id) if inject else r.inject_id
        rating_emoji = {"Best": ":large_green_circle:", "Partial": ":large_yellow_circle:", "Poor": ":red_circle:"}.get(r.rating, "")
        if r.responded_at and r.sent_at:
            elapsed = (r.responded_at - r.sent_at).total_seconds()
            elapsed_text = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        else:
            elapsed_text = "no response"
        lines = [
            f"*{title}* — To: {r.target_role or '?'}",
            f"{rating_emoji} {r.rating or 'No answer'}" + (f" ({r.score}/10)" if r.score is not None else "") + f" — responded in {elapsed_text}" if r.responded_at else f"{rating_emoji} No answer recorded",
        ]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

    return {"blocks": blocks}


def _post_report(run: AIExerciseRun, bot_token: str) -> None:
    if not (run.origin_channel_id and bot_token):
        return
    try:
        _call("chat.postMessage", bot_token, channel=run.origin_channel_id, text="Drill report ready", **build_report_card(run))
    except SlackApiError:
        logger.exception("AI run %s: failed to post report to %s", run.id, run.origin_channel_id)


def _send_inject_dm(run: AIExerciseRun, inject: dict, bot_token: str) -> None:
    role = inject.get("target_role", "")
    recipient = _resolve_recipient(run.team_id, role)
    if not recipient:
        logger.info("AI run %s: no one currently holds role %r -- skipping inject %s", run.id, role, inject.get("inject_id"))
        _fire_next_inject(run, bot_token)
        return

    try:
        opened = _call("conversations.open", bot_token, users=recipient)
        dm_channel_id = opened["channel"]["id"]
    except SlackApiError:
        logger.exception("AI run %s: failed to open DM with %s", run.id, recipient)
        return

    card = _build_inject_card(run, inject, recipient)
    try:
        resp = _call("chat.postMessage", bot_token, channel=dm_channel_id, text=inject.get("title", "Incident update"), **card)
    except SlackApiError:
        logger.exception("AI run %s: failed to send inject %s", run.id, inject.get("inject_id"))
        return

    AIDecisionResponse(
        run=run, inject_id=inject.get("inject_id", ""), decision_id=inject.get("decision_id", ""),
        assigned_slack_user_id=recipient, target_role=role,
        slack_channel_id=dm_channel_id, slack_message_ts=resp.get("ts", ""),
    ).save()


def _build_inject_card(run: AIExerciseRun, inject: dict, recipient: str) -> dict:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f":rotating_light: {inject.get('title', 'Incident update')}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": inject.get("inject_message", "")}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{inject.get('decision_question', '')}*"}},
    ]
    elements = []
    for opt in inject.get("options", []):
        value = f"{run.id}|{inject.get('inject_id', '')}|{opt.get('option', '')}"
        elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": opt.get("option_text", "")[:75], "emoji": True},
                "action_id": f"v2_ai_decision_choose__{opt.get('option', '')}",
                "value": value,
            }
        )
    blocks.append({"type": "actions", "elements": elements})
    return {"blocks": blocks}


def handle_decision(payload: dict, bot_token: str) -> None:
    actions = payload.get("actions") or []
    if not actions:
        return
    action = actions[0]
    value = action.get("value", "")
    run_id, inject_id, option = value.split("|", 2)

    run = AIExerciseRun.objects(id=run_id).first()
    if not run:
        return
    scenario = run.scenario
    inject = _find_inject(scenario, inject_id=inject_id)
    if not inject:
        return

    opt = next((o for o in inject.get("options", []) if o.get("option") == option), None)
    if not opt:
        return

    import datetime

    response = AIDecisionResponse.objects(run=run, inject_id=inject_id).order_by("-sent_at").first()
    if response:
        response.chosen_option = option
        response.score = opt.get("score")
        response.rating = opt.get("rating")
        response.triggers_inject = opt.get("triggers_inject", "-")
        response.responded_at = datetime.datetime.utcnow()
        response.save()

    channel_id = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("message", {}).get("ts", "")
    feedback_card = {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *You chose:* {opt.get('option_text', '')}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": opt.get("feedback", "")}]},
        ]
    }
    if channel_id and message_ts and bot_token:
        try:
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **feedback_card)
        except SlackApiError:
            logger.exception("AI run %s: failed to update inject message with feedback", run.id)

    trigger_id = opt.get("triggers_inject", "-")
    if trigger_id and trigger_id != "-":
        consequence = _find_inject(scenario, inject_id=trigger_id)
        if consequence:
            _send_inject_dm(run, consequence, bot_token)
            return

    _fire_next_inject(run, bot_token)
