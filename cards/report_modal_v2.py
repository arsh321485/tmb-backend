"""
"Preparedness report" on the Live card. Previously always said "no real
data yet" because no real exercise had ever run. Step 6 of Trigger: now
that Steps 1-5 create a real Exercise + real ExerciseTasks with real
response times, this builds the report from that real data -- falls
back to the same honest "no real data yet" message only if there's
truly nothing to show (e.g. a workspace that's never triggered a drill).
"""

import requests

SLACK_API_BASE = "https://slack.com/api"


def _latest_exercise(slack_team_id: str):
    from exercises.models import Exercise

    return Exercise.objects(slack_team_id=slack_team_id).order_by("-created_at").first()


def build_modal_view(slack_team_id: str = "") -> dict:
    exercise = _latest_exercise(slack_team_id) if slack_team_id else None

    if exercise is None:
        blocks = [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": ":bar_chart: *Across all modules*"}]},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*No real data yet.* Trigger a drill first (Step 7) — this report is built from real response times once one has run.",
                },
            },
        ]
        return {"type": "modal", "callback_id": "v2_report_modal", "title": {"type": "plain_text", "text": "Preparedness report"}, "close": {"type": "plain_text", "text": "Close"}, "blocks": blocks}

    from exercises.models import ExerciseTask

    tasks = list(ExerciseTask.objects(exercise=exercise).order_by("sent_at"))
    done = [t for t in tasks if t.status == "done"]
    escalated = [t for t in tasks if t.status == "escalated"]
    pending = [t for t in tasks if t.status == "sent"]
    unacknowledged = [t for t in tasks if not t.was_acknowledged]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":bar_chart: Preparedness report", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{exercise.scenario_name}*  ·  {exercise.module or ''}"}]},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Responded*\n{len(done)} / {len(tasks)}"},
                {"type": "mrkdwn", "text": f"*Escalated to backup*\n{len(escalated)}"},
                {"type": "mrkdwn", "text": f"*Still waiting*\n{len(pending)}"},
                {"type": "mrkdwn", "text": f"*Paged without acknowledging first*\n{len(unacknowledged)} / {len(tasks)}"},
            ],
        },
        {"type": "divider"},
    ]

    if not tasks:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_Nobody was staffed on a team when this drill ran, so nobody was DM'd._"}})

    def _ack_note(t) -> str:
        return "" if t.was_acknowledged else "\n:warning: _Never acknowledged this role before being paged_"

    for t in done:
        elapsed = t.responded_at - t.sent_at
        minutes, seconds = int(elapsed.total_seconds() // 60), int(elapsed.total_seconds() % 60)
        backup_note = " _(was the backup)_" if t.is_backup else ""
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":white_check_mark: *{t.role}* — {t.team_name}{backup_note}\nResponded in {minutes}m {seconds}s{_ack_note(t)}"},
            }
        )

    for t in escalated:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":arrows_counterclockwise: *{t.role}* — {t.team_name}\nPrimary didn't respond in time — handed to backup{_ack_note(t)}"},
            }
        )

    for t in pending:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":hourglass_flowing_sand: *{t.role}* — {t.team_name}\nStill waiting for a response{_ack_note(t)}"},
            }
        )

    # Real decisions + scores (sir's TMP_Ransomware_Injects.xlsx flow) --
    # admin-only: the participant who answered never sees their score or
    # rating, only this report does.
    from exercises.models import DecisionResponse

    decisions = list(DecisionResponse.objects(exercise=exercise).order_by("sent_at"))
    if decisions:
        answered = [d for d in decisions if d.chosen_option]
        poor = [d for d in answered if d.rating == "Poor"]

        time_to_first_text = "—"
        if answered:
            first_sent = min(d.sent_at for d in decisions)
            first_answered = min(d.responded_at for d in answered)
            elapsed = first_answered - first_sent
            minutes, seconds = int(elapsed.total_seconds() // 60), int(elapsed.total_seconds() % 60)
            time_to_first_text = f"{minutes}m {seconds}s"

        blocks.append({"type": "divider"})
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": ":dart: Decisions", "emoji": True}})
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Answered*\n{len(answered)} / {len(decisions)}"},
                    {"type": "mrkdwn", "text": f"*Time to first decision*\n{time_to_first_text}"},
                    {"type": "mrkdwn", "text": f"*Rated Poor*\n{len(poor)} / {len(answered)}" if answered else "*Rated Poor*\n—"},
                ],
            }
        )

        rating_emoji = {"Best": ":white_check_mark:", "Acceptable": ":large_blue_circle:", "Partial": ":large_orange_circle:", "Poor": ":red_circle:"}
        for d in decisions:
            if d.chosen_option:
                emoji = rating_emoji.get(d.rating, ":white_circle:")
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{emoji} *{d.role}* — {d.team_name}\nChose *{d.chosen_option}* · {d.rating} · score {d.score}/10",
                        },
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f":hourglass_flowing_sand: *{d.role}* — {d.team_name}\nDecision not yet answered"},
                    }
                )

    return {"type": "modal", "callback_id": "v2_report_modal", "title": {"type": "plain_text", "text": "Preparedness report"}, "close": {"type": "plain_text", "text": "Close"}, "blocks": blocks}


def open_modal(trigger_id: str, bot_token: str, slack_team_id: str = "") -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(slack_team_id)},
        timeout=10,
    )
