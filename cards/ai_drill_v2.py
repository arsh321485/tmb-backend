"""
A23/A24 -- runs an APPROVED GeneratedScenario (plans/scenario_generator.py)
as a real live drill: sends real DMs to real people, real decision
buttons, real scored answers, real consequence chaining.

The old hand-written plan drill (RW-01/02/03) is removed entirely --
this is now the only drill engine. This file reuses stable, generic
building blocks (the Slack API client, and reading -- never writing --
Team/TeamMember) to avoid any risk of breaking what already works.
"""

import datetime
import logging

from .models_v2 import AIDecisionResponse, AIExerciseRun, GeneratedScenario, RUN_STATUS_COMPLETED, RUN_STATUS_RUNNING, RUN_STATUS_SCHEDULED
from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)

# Same real deadline/escalation behaviour the old fixed-plan drill had --
# an AI-generated decision with no real SLA set still needs a real
# deadline to escalate against.
DEFAULT_RESPONSE_TIMER_MIN = 10


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


def _resolve_backup(team_id: str, role: str, primary_id: str) -> str | None:
    """Same lookup as _resolve_recipient, but the backup Slack user id for
    this role -- used only when the primary misses the real deadline."""
    from .models_v2 import Team, TeamMember

    for team_doc in Team.objects(team_id=team_id):
        tm = TeamMember.objects(team=team_doc, role=role).first()
        if tm and tm.backup_slack_user_ids:
            backup_id = tm.backup_slack_user_ids[0]
            if backup_id and backup_id != primary_id:
                return backup_id
    return None


def build_trigger_picker_card(scenario: GeneratedScenario) -> dict:
    """First real step after Approve (flowchart's "Training mode?" box).
    Same exact layout as the fixed-plan path's own Trigger screen
    (trigger_v2_data.build_training_mode_card) -- sir's call: one
    Trigger screen design, not a second plainer one just because this
    scenario came from the AI instead of the hand-built catalog. Yes
    sends everyone a real pre-notification DM before anything else
    happens; No skips straight to the Trigger/Schedule/Surprise picker."""
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":zap: Step 7 · Trigger", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
            {"type": "section", "text": {"type": "mrkdwn", "text": ":bell: *Training mode?*\nChoose how the team finds out this is starting."}},
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": ":mega: *Yes · Pre-notify*\n_Heads-up DM sent first_"},
                    {"type": "mrkdwn", "text": ":dash: *No · Go live*\n_No warning, starts immediately_"},
                ],
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": ":mega: Yes -- send pre-notification", "emoji": True}, "action_id": "v2_ai_training_yes", "value": str(scenario.id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": ":dash: No -- send test directly", "emoji": True}, "action_id": "v2_ai_training_no", "value": str(scenario.id)},
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":bulb: Training mode is the safer default for a first-time or new-team drill."}],
            },
        ]
    }


def build_timing_picker_card(scenario: GeneratedScenario, training_mode: bool, picked: str = "") -> dict:
    """Same exact layout as the fixed-plan path's own Trigger/when-to-run
    screen (trigger_v2_data.build_trigger_card, same TRIGGERS list) --
    sir's call, same as build_trigger_picker_card above: one screen
    design for this, not a second one just for AI scenarios."""
    from .trigger_v2_data import TRIGGERS

    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"
    mode_note = ":white_check_mark: Pre-notification sent." if training_mode else "Sending directly -- no advance warning."
    value_suffix = f"{scenario.id}|{int(training_mode)}"
    action_for_key = {"now": "v2_ai_trigger_now", "sched": "v2_ai_trigger_schedule_open", "surprise": "v2_ai_trigger_surprise"}

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":zap: Step 7 · Trigger", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_  ·  {mode_note}"}]},
        {"type": "divider"},
    ]
    for key, icon, label, desc in TRIGGERS:
        is_picked = key == picked
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": (":white_check_mark: " if is_picked else f"{icon} ") + f"*{label}*\n{desc}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Picked" if is_picked else "Choose", "emoji": True},
                    "action_id": action_for_key[key],
                    "value": value_suffix,
                    **({"style": "danger"} if key == "now" and not picked else {}),
                },
            }
        )
        blocks.append({"type": "divider"})
    return {"blocks": blocks}


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
    """Same exact "Live" screen layout as the fixed-plan path
    (trigger_v2_data.build_live_card) -- sir's call, same reasoning as
    the Trigger screens above: an AI scenario is a normal part of this
    app now, not a separate feature with its own look. Unlike that
    screen's placeholder fields ("not built yet"), these are real
    counts from this run's actual AIDecisionResponse rows."""
    breadcrumb = f"{scenario.threat_label}  ›  {scenario.incident_name}  ›  {scenario.cause_name}"

    if run.status == RUN_STATUS_SCHEDULED:
        status_text = f":alarm_clock: *Scheduled*  ·  {run.scheduled_at.strftime('%d %b %Y, %H:%M UTC')}"
    elif run.status == RUN_STATUS_RUNNING:
        status_text = ":fire: *Live now*  ·  injects are going out to real people"
    else:
        status_text = ":checkered_flag: *Completed*"

    responses = AIDecisionResponse.objects(run=run)
    notified_count = len(responses.distinct("assigned_slack_user_id"))
    total_injects = len(scenario.injects)
    answered_count = responses.filter(responded_at__ne=None).count()
    scored = [r for r in responses if r.score is not None]
    total_score = sum(r.score for r in scored)
    max_possible = sum(10 for _ in scored)

    participants_text = f"{notified_count} real {'person' if notified_count == 1 else 'people'} DM'd so far" if notified_count else "Nobody reached yet"
    injects_text = f"{total_injects - answered_count} / {total_injects} remaining" if total_injects else "0"
    scoring_text = f"{total_score} / {max_possible}" if scored else "No decisions answered yet"

    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": breadcrumb, "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": status_text}]},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "The test is running. You can watch, inject complications, or pull the report at any time.",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Participants notified*\n{participants_text}"},
                    {"type": "mrkdwn", "text": f"*Injects remaining*\n{injects_text}"},
                    {"type": "mrkdwn", "text": f"*Scoring*\n{scoring_text}"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Preparedness report", "emoji": True},
                        "action_id": "v2_ai_live_report",
                        "value": str(run.id),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Inject a scenario", "emoji": True},
                        "action_id": "v2_live_inject",
                        "value": "inject",
                        "style": "danger",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Run another test", "emoji": True},
                        "action_id": "v2_nav_jump__welcome",
                        "value": "new",
                    },
                ],
            },
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
        # Sir's call: finishing the last question never posts or updates
        # anything on its own -- the report only ever shows up when the
        # admin actually clicks "Preparedness report" (still sitting
        # right there on the Live card they already have open), which
        # opens it as the real popup every time, same as a manual click
        # mid-drill already does.
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


def build_report_modal_view(run: AIExerciseRun) -> dict:
    """Same report content as build_report_card, as a real popup modal
    instead of replacing the Live screen -- sir's call: "Preparedness
    report" should behave the same way here as it already does on the
    fixed-plan path (cards/report_modal_v2.py), not open a separate new
    full-screen card just because this run came from an AI scenario."""
    card = build_report_card(run)
    return {
        "type": "modal",
        "callback_id": "v2_ai_report_modal",
        "title": {"type": "plain_text", "text": "Preparedness report"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": card["blocks"],
    }


def _send_inject_dm(run: AIExerciseRun, inject: dict, bot_token: str, recipient: str | None = None, is_backup: bool = False) -> None:
    role = inject.get("target_role", "")
    if not recipient:
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

    timer_min = inject.get("response_timer_min") or DEFAULT_RESPONSE_TIMER_MIN
    due_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=timer_min)

    card = _build_inject_card(run, inject, recipient, due_at, is_backup=is_backup)
    try:
        resp = _call("chat.postMessage", bot_token, channel=dm_channel_id, text=inject.get("title", "Incident update"), **card)
    except SlackApiError:
        logger.exception("AI run %s: failed to send inject %s", run.id, inject.get("inject_id"))
        return

    AIDecisionResponse(
        run=run, inject_id=inject.get("inject_id", ""), decision_id=inject.get("decision_id", ""),
        assigned_slack_user_id=recipient, target_role=role,
        slack_channel_id=dm_channel_id, slack_message_ts=resp.get("ts", ""),
        due_at=due_at, is_backup=is_backup,
    ).save()


def _history_blocks(run: AIExerciseRun) -> list:
    """
    Same real trail the old fixed-plan drill showed (sir's call): each new
    decision card lists what's already been decided earlier in THIS run --
    role, the question they were asked, and what they chose -- so the next
    person has the same situational awareness a real incident would give
    them, instead of deciding blind. Score/rating stay admin-only, never
    shown here.
    """
    scenario = run.scenario
    answered = list(AIDecisionResponse.objects(run=run, chosen_option__ne=None).order_by("sent_at"))
    if not answered:
        return []

    lines = []
    for d in answered:
        inject = _find_inject(scenario, inject_id=d.inject_id)
        option = next((o for o in (inject.get("options", []) if inject else []) if o.get("option") == d.chosen_option), None)
        if not inject or not option:
            continue
        role_label = d.target_role or "?"
        lines.append(f"✓ *{role_label}* — _{inject.get('decision_question', '')}_\n→ {option.get('option_text', '')}")

    if not lines:
        return []

    blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": "`DECISIONS SO FAR`"}]}]
    # Chunked the same way the rest of this app's long lists are -- keeps
    # each section block comfortably under Slack's 3000-char text limit
    # even on a run with many prior decisions.
    for chunk_start in range(0, len(lines), 4):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(lines[chunk_start:chunk_start + 4])}})
    blocks.append({"type": "divider"})
    return blocks


def _build_inject_card(run: AIExerciseRun, inject: dict, recipient: str, due_at=None, is_backup: bool = False) -> dict:
    headline = f":arrows_counterclockwise: {inject.get('title', 'Incident update')} — primary didn't respond in time" if is_backup else f":rotating_light: {inject.get('title', 'Incident update')}"

    # Same real deadline display as the rest of this app's decision cards --
    # Slack's <!date^...> renders in the VIEWER's own local timezone.
    question_label = "`DECISION QUESTION`"
    if due_at:
        ts = int(due_at.replace(tzinfo=datetime.timezone.utc).timestamp())
        question_label += f"   ·   :stopwatch: Respond by <!date^{ts}^{{date_short_pretty}} at {{time}}|the deadline>"

    blocks = [
        *_history_blocks(run),
        {"type": "header", "text": {"type": "plain_text", "text": headline, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": inject.get("inject_message", "")}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": question_label}]},
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

    # Confirmed live: a "Poor" answer with a consequence attached sent
    # that one informational DM and then the drill just stopped dead --
    # nothing here ever continued on to the next real Main inject,
    # because this used to `return` right after the consequence instead
    # of falling through to _fire_next_inject like every other path
    # does. The consequence has no decision of its own to wait on, so
    # there's nothing to block the sequence continuing right after it.
    trigger_id = opt.get("triggers_inject", "-")
    if trigger_id and trigger_id != "-":
        consequence = _find_inject(scenario, inject_id=trigger_id)
        if consequence:
            _send_inject_dm(run, consequence, bot_token)

    _fire_next_inject(run, bot_token)


def escalate_overdue_ai_decisions() -> int:
    """
    Real timeout handling for AI-generated drill decisions, same rule as
    the old fixed-plan drill: past its real due_at and still unanswered,
    page the real backup for that role with the same inject, or (no
    backup, or the backup also missed it) auto-resolve it as a missed
    decision -- scored as the worst real option on file -- and let the
    chain continue rather than hanging the drill forever. Meant to be
    called on a recurring timer (see exercises/apps.py).
    """
    from workspaces.models import get_bot_token

    overdue = AIDecisionResponse.objects(chosen_option=None, escalated=False, due_at__lt=datetime.datetime.utcnow())

    count = 0
    for response in overdue:
        response.escalated = True
        response.save()

        run = response.run
        if not run or run.status != RUN_STATUS_RUNNING:
            continue

        bot_token = get_bot_token(run.team_id)
        if not bot_token:
            continue

        scenario = run.scenario
        inject = _find_inject(scenario, inject_id=response.inject_id)
        if not inject:
            continue

        backup_id = None
        if not response.is_backup:
            backup_id = _resolve_backup(run.team_id, response.target_role, response.assigned_slack_user_id)

        if backup_id:
            _send_inject_dm(run, inject, bot_token, recipient=backup_id, is_backup=True)
        else:
            # No real backup to page (or the backup already missed it too)
            # -- honest "nobody decided" outcome, worst score on file.
            response.timed_out = True
            response.chosen_option = ""
            response.score = 0
            response.rating = "Poor"
            response.responded_at = datetime.datetime.utcnow()
            response.save()

            if response.slack_channel_id and response.slack_message_ts:
                try:
                    _call(
                        "chat.update",
                        bot_token,
                        channel=response.slack_channel_id,
                        ts=response.slack_message_ts,
                        text="Decision timed out",
                        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": ":hourglass: *This decision timed out* — no response was recorded in time."}}],
                    )
                except SlackApiError:
                    logger.exception("Failed to update timed-out AI decision DM for response %s", response.id)

            consequence_trigger = next((o.get("triggers_inject") for o in inject.get("options", []) if o.get("rating") == "Poor"), None)
            if consequence_trigger and consequence_trigger != "-":
                consequence = _find_inject(scenario, inject_id=consequence_trigger)
                if consequence:
                    _send_inject_dm(run, consequence, bot_token)

            _fire_next_inject(run, bot_token)

        count += 1

    return count
