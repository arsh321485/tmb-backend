"""
Real injects + scored decisions during a live drill (sir's
TMP_Ransomware_Injects.xlsx -- Injects + Decision Options sheets).

Flow: the drill fires the first inject to its real target role(s) -> they
pick one of 2-4 options -> they see ONLY the feedback text for their pick
(never the score/rating -- that's admin-only, read from DecisionResponse)
-> a poor choice can chain into a "Consequence" inject automatically;
otherwise the next inject in the plan's real sequence goes out.
"""

import datetime
import logging

from .slack_client import SlackApiError, _call

logger = logging.getLogger(__name__)

# Real spreadsheet timers run 10-15 min -- a decision with no timer at
# all in the data still needs a real deadline to escalate against.
DEFAULT_RESPONSE_TIMER_MIN = 15


def _resolve_recipients(slack_team_id: str, target_team_ids: str, target_roles: str) -> list:
    """
    Target Team IDs / Target Roles are two lists ("T01, T02" / "Role A |
    Role B") -- NOT reliably in matching order (confirmed against real
    data: e.g. "T01, T02, T05" against "SOC Tier 2 | IC | Legal" pairs
    positionally wrong on the first two). Each role is matched to
    whichever of the listed teams actually owns it in the real catalog,
    not by position.
    """
    from .models_v2 import Team, TeamMember
    from .team_catalog_v2 import find_team, roles_for_team

    team_ids = [t.strip() for t in (target_team_ids or "").split(",") if t.strip()]
    roles = [r.strip() for r in (target_roles or "").split("|") if r.strip()]

    recipients = []
    for role in roles:
        owning_team_id = next(
            (tid for tid in team_ids if any(r["role"] == role for r in roles_for_team(tid))),
            None,
        )
        if not owning_team_id:
            logger.warning("No team in %s owns role %r -- skipped", team_ids, role)
            continue

        team_info = find_team(owning_team_id)
        team_name = team_info["name"] if team_info else owning_team_id
        team_doc = Team.objects(team_id=slack_team_id, slug=owning_team_id).first()
        tm = TeamMember.objects(team=team_doc, role=role).first() if team_doc else None
        primary_id = tm.primary_slack_user_ids[0] if tm and tm.primary_slack_user_ids else ""
        if primary_id:
            recipients.append((team_name, role, primary_id))
    return recipients


def send_inject(exercise, inject: dict, bot_token: str, resume_seq: int | None = None) -> None:
    """
    DMs the real target role(s) for this inject, with the decision
    question and option buttons, and creates one DecisionResponse per
    recipient to track their (admin-only) score once they answer.

    resume_seq is the Main-sequence position to come back to once any
    chain of Consequence injects stemming from this one finishes --
    for a Main inject this is just its own seq; for a Consequence
    inject (no seq of its own) it's passed through from whichever
    answer triggered it, so the chain can find its way back to the
    next real Main inject afterward.
    """
    from .inject_catalog_v2 import options_for_decision
    from exercises.models import DecisionResponse

    recipients = _resolve_recipients(exercise.slack_team_id, inject["target_team_ids"], inject["target_roles"])
    if not recipients:
        logger.info("Inject %s has no real recipients staffed yet -- skipped", inject["inject_id"])
        return

    options = options_for_decision(inject["decision_id"])
    if resume_seq is None:
        resume_seq = inject.get("seq")

    timer_min = inject.get("response_timer_min") or DEFAULT_RESPONSE_TIMER_MIN
    due_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=timer_min)

    for team_name, role, user_id in recipients:
        response = DecisionResponse(
            exercise=exercise,
            inject_id=inject["inject_id"],
            decision_id=inject["decision_id"],
            assigned_slack_user_id=user_id,
            team_name=team_name,
            role=role,
            resume_seq=resume_seq,
            due_at=due_at,
        )
        response.save()

        try:
            _send_decision_dm(response, inject, options, bot_token)
        except SlackApiError:
            logger.exception("Failed to DM inject %s to %s", inject["inject_id"], user_id)


def _option_line(o: dict) -> str:
    return f"*{o['option']})* {o['option_text']}"


def _history_blocks(exercise) -> list:
    """
    Sir's call: each new decision card shows the real trail of what's
    already been decided in this drill -- role, the question they were
    asked, and what they chose -- so the next person has the same
    situational awareness a real incident would give them (SOC escalates,
    IR Lead should see what SOC actually found, not decide blind). Score
    and rating are never included here -- those stay admin-only.
    """
    from .inject_catalog_v2 import find_inject, find_option
    from exercises.models import DecisionResponse

    answered = list(DecisionResponse.objects(exercise=exercise, chosen_option__ne=None).order_by("sent_at"))
    if not answered:
        return []

    lines = []
    for d in answered:
        inject = find_inject(d.inject_id)
        option = find_option(d.decision_id, d.chosen_option)
        if not inject or not option:
            continue
        lines.append(f"✓ *{d.role}* — _{inject['decision_question']}_\n→ {option['option_text']}")

    if not lines:
        return []

    blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": "`DECISIONS SO FAR`"}]}]
    # Chunked the same way the plan summary is -- keeps each section
    # block comfortably under Slack's 3000-char text limit even on a
    # phase with many prior decisions.
    for chunk_start in range(0, len(lines), 4):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(lines[chunk_start:chunk_start + 4])}})
    blocks.append({"type": "divider"})
    return blocks


def build_preview_blocks(response, inject: dict, options: list, selected_option: str = "") -> list:
    """
    The DM itself -- real select-then-Submit, inline, no modal: a row of
    A/B/C/D buttons where clicking one re-renders the message marking it
    selected (style "primary"), same pattern as every other tab-style
    pick in this app (block_id carries the current selection so it
    survives the next click) -- then a separate Submit button reads
    whichever option is currently marked selected and finalises it.
    """
    headline = f":arrows_counterclockwise: {inject['title']} — primary didn't respond in time" if response.is_backup else f":rotating_light: {inject['title']}"

    # Slack's <!date^...> renders in the VIEWER's own local timezone
    # automatically -- a real deadline clock-time, not just "within X
    # minutes". If it's missed, escalate_overdue_decisions (checked every
    # 60s, same as task/schedule checks) DMs the backup for real, same as
    # task escalation. Shown right beside the DECISION QUESTION label.
    question_label = "`DECISION QUESTION`"
    if response.due_at:
        ts = int(response.due_at.replace(tzinfo=datetime.timezone.utc).timestamp())
        question_label += f"   ·   :stopwatch: Respond by <!date^{ts}^{{date_short_pretty}} at {{time}}|the deadline>"

    blocks = [
        *_history_blocks(response.exercise),
        {"type": "header", "text": {"type": "plain_text", "text": headline, "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*Team*  {response.team_name}   ·   :dart: *Decision Owner*  `{response.role}`"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": inject["inject_message"]}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": question_label}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{inject['decision_question']}*"}},
    ]
    for o in options:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _option_line(o)}})

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"decisionoptionpick|{response.id}|{selected_option}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": o["option"], "emoji": True},
                    "action_id": f"v2_decision_select__{o['option']}",
                    "value": str(response.id),
                    **({"style": "primary"} if o["option"] == selected_option else {}),
                }
                for o in options
            ],
        }
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Submit Decision", "emoji": True},
                    "action_id": "v2_decision_submit",
                    "value": str(response.id),
                    "style": "primary" if selected_option else "danger",
                }
            ],
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "This is a readiness drill, not a real incident. "
                    + (f"Option *{selected_option}* selected — click Submit to answer." if selected_option else "Select an option, then click Submit."),
                }
            ],
        }
    )
    return blocks


def _send_decision_dm(response, inject: dict, options: list, bot_token: str) -> None:
    opened = _call("conversations.open", bot_token, users=response.assigned_slack_user_id)
    dm_channel_id = opened["channel"]["id"]

    blocks = build_preview_blocks(response, inject, options)
    sent = _call(
        "chat.postMessage",
        bot_token,
        channel=dm_channel_id,
        text=f"Decision needed: {inject['decision_question']}",
        blocks=blocks,
    )
    response.slack_channel_id = dm_channel_id
    response.slack_message_ts = sent.get("ts", "")
    response.save()


def handle_decision_select(response_id: str, option: str, channel_id: str, message_ts: str, bot_token: str) -> None:
    """Marks `option` as the currently-selected one -- re-renders the DM
    with that button highlighted, same as clicking a different tab
    elsewhere in this app. Doesn't score or finalise anything; that only
    happens on Submit."""
    from .inject_catalog_v2 import find_inject, options_for_decision
    from exercises.models import DecisionResponse

    response = DecisionResponse.objects(id=response_id).first()
    if not response or response.chosen_option:
        return  # already answered -- ignore further clicks

    inject = find_inject(response.inject_id)
    if not inject or not channel_id or not message_ts:
        return
    options = options_for_decision(response.decision_id)

    blocks = build_preview_blocks(response, inject, options, selected_option=option)
    try:
        _call("chat.update", bot_token, channel=channel_id, ts=message_ts, text="Decision needed", blocks=blocks)
    except SlackApiError:
        logger.exception("Failed to update decision selection for response %s", response_id)


def handle_decision_submit(response_id: str, message_blocks: list, bot_token: str) -> None:
    """Reads whichever option is currently highlighted (from the message's
    own block_id, same as every other tab-style read in this app) and
    finalises it through handle_decision_pick."""
    selected_option = ""
    for block in message_blocks or []:
        block_id = block.get("block_id", "")
        if block_id.startswith(f"decisionoptionpick|{response_id}|"):
            selected_option = block_id.removeprefix(f"decisionoptionpick|{response_id}|")
            break

    if selected_option:
        handle_decision_pick(response_id, selected_option, bot_token)


def _advance_chain(response, bot_token: str) -> None:
    """
    Shared by a real answer and an auto-resolved timeout: finds whatever
    comes next (the triggered consequence inject, or the next Main inject
    in the plan's real sequence), honouring the phase boundary, and sends
    it.
    """
    from .inject_catalog_v2 import find_inject, injects_for_plan

    exercise = response.exercise
    plan_id = exercise.module  # reused to carry the real plan_id for this flow -- see v2_trigger_pick__

    next_inject = None
    next_resume_seq = response.resume_seq
    if response.triggered_inject_id:
        # Stay on the same detour -- a Consequence inject can itself lead
        # to another Consequence inject, so this doesn't touch resume_seq;
        # it's only used again once the chain gets back to a non-triggering
        # answer below.
        next_inject = find_inject(response.triggered_inject_id)
    elif response.resume_seq is not None:
        sequence = injects_for_plan(plan_id)
        later = [i for i in sequence if i["seq"] > response.resume_seq]
        next_inject = later[0] if later else None
        next_resume_seq = next_inject["seq"] if next_inject else None

    # Phase-scoped drill (sir's call: trigger one Phase at a time, not
    # the whole plan) -- stop the chain the moment it would cross into a
    # different phase than the one this drill was armed for, instead of
    # continuing straight through every remaining phase.
    if next_inject and exercise.inject_phase and next_inject.get("phase") != exercise.inject_phase:
        next_inject = None

    if next_inject:
        send_inject(exercise, next_inject, bot_token, resume_seq=next_resume_seq)


def handle_decision_pick(response_id: str, option: str, bot_token: str) -> None:
    """
    Records the real score/rating (admin-only), shows the participant
    ONLY the feedback text, then chains into the consequence inject if
    this option triggers one -- otherwise releases the next Main inject
    in the plan's real sequence.
    """
    from .inject_catalog_v2 import find_option
    from exercises.models import DecisionResponse

    response = DecisionResponse.objects(id=response_id).first()
    if not response or response.chosen_option:
        return  # already answered, or gone -- nothing to do

    picked = find_option(response.decision_id, option)
    if not picked:
        return

    response.chosen_option = option
    response.score = picked.get("score")
    response.rating = picked.get("rating")
    response.responded_at = datetime.datetime.utcnow()
    triggers = picked.get("triggers_inject")
    if triggers and triggers != "-":
        response.triggered_inject_id = triggers
    response.save()

    # Replace the DM's buttons with just the feedback -- never the score.
    if response.slack_channel_id and response.slack_message_ts:
        feedback_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *You chose option {option}.*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": picked.get("feedback", "")}},
        ]
        try:
            _call(
                "chat.update",
                bot_token,
                channel=response.slack_channel_id,
                ts=response.slack_message_ts,
                text="Decision recorded",
                blocks=feedback_blocks,
            )
        except SlackApiError:
            logger.exception("Failed to update decision DM for response %s", response_id)

    _advance_chain(response, bot_token)


def escalate_overdue_decisions() -> int:
    """
    Real timeout handling for decisions (sir's call) -- finds every
    decision still unanswered past its real due_at, and either pages the
    real backup for that (team, role) with the SAME decision, or, if
    there's no backup (or the backup also timed out), auto-resolves it
    as a missed decision and lets the chain continue rather than hanging
    the drill forever. Meant to be called on a recurring timer (see
    exercises/apps.py), same pattern as escalate_overdue_tasks.
    """
    from .inject_catalog_v2 import find_inject, options_for_decision
    from .models_v2 import Team, TeamMember
    from exercises.models import DecisionResponse
    from workspaces.models import get_bot_token

    overdue = DecisionResponse.objects(chosen_option=None, escalated=False, due_at__lt=datetime.datetime.utcnow())

    count = 0
    for response in overdue:
        response.escalated = True
        response.save()

        exercise = response.exercise
        bot_token = get_bot_token(exercise.slack_team_id) if exercise else None
        if not bot_token:
            continue

        inject = find_inject(response.inject_id)
        if not inject:
            continue

        backup_id = ""
        if not response.is_backup:
            # Narrow to the exact team that owns this role (same
            # resolution rule as _resolve_recipients -- role name decides
            # the team, not list position).
            team_ids = [tid.strip() for tid in inject["target_team_ids"].split(",") if tid.strip()]
            team_doc = None
            for tid in team_ids:
                candidate = Team.objects(team_id=exercise.slack_team_id, slug=tid).first()
                if candidate and TeamMember.objects(team=candidate, role=response.role).first():
                    team_doc = candidate
                    break
            tm = TeamMember.objects(team=team_doc, role=response.role).first() if team_doc else None
            if tm and tm.backup_slack_user_ids:
                backup_id = tm.backup_slack_user_ids[0]

        if backup_id and backup_id != response.assigned_slack_user_id:
            backup_response = DecisionResponse(
                exercise=exercise,
                inject_id=response.inject_id,
                decision_id=response.decision_id,
                assigned_slack_user_id=backup_id,
                team_name=response.team_name,
                role=response.role,
                resume_seq=response.resume_seq,
                is_backup=True,
                due_at=datetime.datetime.utcnow() + datetime.timedelta(
                    minutes=inject.get("response_timer_min") or DEFAULT_RESPONSE_TIMER_MIN
                ),
            )
            backup_response.save()
            options = options_for_decision(inject["decision_id"])
            try:
                _send_decision_dm(backup_response, inject, options, bot_token)
            except SlackApiError:
                logger.exception("Failed to DM backup for overdue decision %s", response.id)
        else:
            # No real backup to page (or the backup already missed it
            # too) -- score it as the worst real option on file (the
            # honest "nobody decided" outcome, matching the Field
            # Manual's 0-3 rubric's bottom score) and let the chain
            # continue instead of stalling the drill indefinitely.
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
                    logger.exception("Failed to update timed-out decision DM for response %s", response.id)

            _advance_chain(response, bot_token)

        count += 1

    return count
