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

    # Rendered as a real image (sir's design) -- logo+badge, breadcrumb,
    # title, and the two option boxes. No per-item click target in any
    # of that (only the two real buttons below actually choose
    # something), so it's all safe to bake in.
    from django.conf import settings

    from .trigger_training_card_image import get_trigger_training_card_image_url

    image_url = get_trigger_training_card_image_url(settings.BACKEND_URL, breadcrumb)
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Training mode?"},
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
    value_suffix = f"{scenario.id}|{int(training_mode)}"
    action_for_key = {"now": "v2_ai_trigger_now", "sched": "v2_ai_trigger_schedule_open", "surprise": "v2_ai_trigger_surprise"}

    # Rendered as a real image (sir's dark-theme design) -- logo+badge,
    # breadcrumb, the pre-notification pill, title, and the three
    # timing tiles. None of that is a per-item click target (the real
    # buttons below are what actually picks one), so it's all safe to
    # bake in.
    from django.conf import settings

    from .trigger_timing_card_image import get_trigger_timing_card_image_url

    image_url = get_trigger_timing_card_image_url(settings.BACKEND_URL, breadcrumb, training_mode)
    blocks = [
        {"type": "image", "image_url": image_url, "alt_text": "When should it fire?"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ("Picked" if key == picked else f"{icon} {label}"), "emoji": True},
                    "action_id": action_for_key[key],
                    "value": value_suffix,
                    **({"style": "danger"} if key == "now" and not picked else {}),
                }
                for key, icon, label, desc in TRIGGERS
            ],
        },
    ]
    return {"blocks": blocks}


def send_pre_notification(scenario: GeneratedScenario, bot_token: str) -> int:
    """Training mode = Yes: a real heads-up DM (sir's "A drill with your
    role runs soon" design, cards/heads_up_card_image.py) to every real
    person who holds a role targeted anywhere in this scenario, before
    anything else fires. Returns how many people were actually
    reached."""
    from django.conf import settings

    from .heads_up_card_image import get_heads_up_card_image_url

    roles = {inj.get("target_role", "") for inj in scenario.injects if inj.get("target_role")}
    # cause_name is "cause1 + cause2 + ..." for an incident-wide scenario
    # (incident_test_v2.get_or_generate_incident_scenario joins it this
    # way), or just one cause name for the older per-cause path -- split
    # back apart so the Causes box can list each one on its own line.
    causes = [c.strip() for c in (scenario.cause_name or "").split(" + ") if c.strip()]
    sent_to = set()
    for role in roles:
        recipient = _resolve_recipient(scenario.team_id, role)
        if not recipient or recipient in sent_to:
            continue
        try:
            opened = _call("conversations.open", bot_token, users=recipient)
            dm_channel_id = opened["channel"]["id"]
            image_url = get_heads_up_card_image_url(settings.BACKEND_URL, scenario.threat_label, scenario.incident_name, causes, role)
            _call(
                "chat.postMessage", bot_token, channel=dm_channel_id,
                text=f"Heads up -- a TestMyPlan drill involving your role ({role}) will run soon.",
                blocks=[{"type": "image", "image_url": image_url, "alt_text": "A drill with your role runs soon"}],
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
        title_suffix = "scheduled."
        subtitle = f"Starts {run.scheduled_at.strftime('%d %b %Y, %H:%M UTC')}. You can watch, inject complications, or pull the report once it's live."
    elif run.status == RUN_STATUS_RUNNING:
        title_suffix = "running."
        subtitle = "Injects are going out to real people. Watch, inject complications, or pull the report at any time."
    else:
        title_suffix = "complete."
        subtitle = "Every inject has been sent. Pull the report to see how the team did."

    responses = AIDecisionResponse.objects(run=run)
    notified_count = len(responses.distinct("assigned_slack_user_id"))
    total_injects = len(scenario.injects)
    answered_count = responses.filter(responded_at__ne=None).count()
    scored = [r for r in responses if r.score is not None]
    total_score = sum(r.score for r in scored)
    max_possible = sum(10 for _ in scored)

    participants_caption = f"Real {'person' if notified_count == 1 else 'people'} DM'd so far" if notified_count else "Nobody reached yet"
    injects_caption = f"{answered_count} answered" if answered_count else "None sent yet"
    scoring_caption = "No decisions answered yet" if not scored else ""

    badge_text = {
        RUN_STATUS_SCHEDULED: "SCHEDULED",
        RUN_STATUS_RUNNING: "LIVE NOW",
    }.get(run.status, "COMPLETED")

    # Rendered as a real image (sir's dark-theme design) -- logo+badge,
    # breadcrumb, title, subtitle, and the three stat tiles. None of
    # that is a per-item click target, so it's all safe to bake in.
    from django.conf import settings

    from .live_status_card_image import get_live_status_card_image_url

    scoring_value = f"{total_score} / {max_possible}" if scored else "—"
    image_url = get_live_status_card_image_url(
        settings.BACKEND_URL, breadcrumb, badge_text, title_suffix, subtitle,
        f"{notified_count}\n{participants_caption}",
        f"{total_injects - answered_count}/{total_injects}\n{injects_caption}",
        f"{scoring_value}\n{scoring_caption}",
    )

    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "The test is running"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Preparedness report", "emoji": True},
                        "action_id": "v2_ai_drill_overview",
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


def build_drill_overview_card(run: AIExerciseRun) -> dict:
    """Drill Analytics · Overview -- real preparedness score, planned-
    vs-actual response time, and per-phase breakdown, all computed in
    cards/drill_analytics.py from this run's actual AIDecisionResponse
    rows. "Team breakdown" is the only further-drill-down button
    wired up today (see that module's docstring for why RTO/RPO and
    privacy-breach views aren't built yet -- they need a drill
    mechanic this app doesn't capture data for)."""
    from django.conf import settings

    from . import drill_analytics
    from .drill_analytics_card_image import get_overview_image_url

    data = drill_analytics.compute_overview(run)
    image_url = get_overview_image_url(settings.BACKEND_URL, data)

    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Drill analytics overview"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Team breakdown", "emoji": True},
                        "action_id": "v2_ai_drill_team_breakdown",
                        "value": str(run.id),
                        "style": "primary",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Preparedness compares planned with actual response time, summed across every team in the drill."}],
            },
        ]
    }


def build_drill_team_breakdown_card(run: AIExerciseRun) -> dict:
    """Drill Analytics · Team breakdown -- per-team planned-vs-actual
    deviation, ranked slowest-first, plus a real bottleneck (the
    single slowest answered decision) and single-point-of-failure
    (a team only one person ever answered for) when the data shows
    one -- both observed facts from who actually answered, not
    invented narratives."""
    from django.conf import settings

    from . import drill_analytics
    from .drill_analytics_card_image import get_team_breakdown_image_url

    data = drill_analytics.compute_team_breakdown(run)
    image_url = get_team_breakdown_image_url(settings.BACKEND_URL, data)
    return {
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": "Where the time went"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "← Overview", "emoji": True},
                        "action_id": "v2_ai_drill_overview",
                        "value": str(run.id),
                    },
                ],
            },
        ]
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


def _build_inject_card(run: AIExerciseRun, inject: dict, recipient: str, due_at=None, is_backup: bool = False) -> dict:
    from django.conf import settings

    from .decision_card_image import get_decision_card_image_url

    scenario = run.scenario
    phases_present = [p for p in scenario.phases if any(i.get("phase") == p for i in scenario.injects)]
    active_phase = inject.get("phase", "")
    injects_by_seq = sorted(scenario.injects, key=lambda i: i.get("seq", 0))
    decision_number = next((idx + 1 for idx, i in enumerate(injects_by_seq) if i.get("inject_id") == inject.get("inject_id")), 1)
    total_decisions = len(injects_by_seq)
    inject_message = inject.get("inject_message", "")
    decision_question = inject.get("decision_question", "")
    options = inject.get("options", [])
    option_texts = [opt.get("option_text", "") for opt in options]
    image_url = get_decision_card_image_url(
        settings.BACKEND_URL, phases_present, active_phase, decision_number, total_decisions,
        inject_message, decision_question, option_texts,
    )

    # Confirmed live: each new question used to arrive bundled together
    # with the "decisions so far" recap of every PRIOR answer, all in
    # the same message/screen as the new question -- sir's call: each
    # new decision card should be its own clean screen, not combined
    # with the history trail.
    blocks = [
        {"type": "image", "image_url": image_url, "alt_text": f"Decision {decision_number} of {total_decisions} — {active_phase}"},
    ]
    if is_backup:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f":arrows_counterclockwise: {inject.get('title', 'Incident update')} — primary didn't respond in time"}]})

    # Same real deadline display as the rest of this app's decision cards --
    # Slack's <!date^...> renders in the VIEWER's own local timezone, so
    # it has to stay real Slack text, not something baked into the image
    # above (which is the same bytes for every viewer).
    question_label = "`DECISION QUESTION`"
    if due_at:
        ts = int(due_at.replace(tzinfo=datetime.timezone.utc).timestamp())
        question_label += f"   ·   :stopwatch: Respond by <!date^{ts}^{{date_short_pretty}} at {{time}}|the deadline>"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": question_label}]})

    # Every option's full wording is already shown inside the image
    # above (with its own A/B/C badge), so these only need to be the
    # bare letters -- the actual click still has to be a real Slack
    # button (Slack can't pin one to a spot inside a picture), but it
    # doesn't need to repeat the option text sir's design already shows.
    elements = []
    for letter, opt in zip("ABCDEFG", options):
        value = f"{run.id}|{inject.get('inject_id', '')}|{opt.get('option', '')}"
        elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": letter, "emoji": False},
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

    from django.conf import settings

    from .decision_confirm_card_image import get_decision_confirm_card_image_url

    response = AIDecisionResponse.objects(run=run, inject_id=inject_id).order_by("-sent_at").first()
    responded_at = datetime.datetime.utcnow()
    if response:
        response.chosen_option = option
        response.score = opt.get("score")
        response.rating = opt.get("rating")
        response.triggers_inject = opt.get("triggers_inject", "-")
        response.responded_at = responded_at
        response.save()

    options = inject.get("options", [])
    letter_idx = next((i for i, o in enumerate(options) if o.get("option") == option), 0)
    letter = "ABCDEFG"[letter_idx] if letter_idx < 7 else "?"
    role_label = response.target_role if response and response.target_role else "?"
    if response and response.sent_at:
        elapsed = int((responded_at - response.sent_at).total_seconds())
        time_to_decide = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
    else:
        time_to_decide = "—"

    channel_id = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("message", {}).get("ts", "")
    image_url = get_decision_confirm_card_image_url(
        settings.BACKEND_URL, letter, opt.get("option_text", ""), role_label, time_to_decide, "Arrives when the team is ready",
    )
    feedback_card = {"blocks": [{"type": "image", "image_url": image_url, "alt_text": "Your answer is in"}]}
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
