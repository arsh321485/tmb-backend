"""Step 7 · Trigger, and Step 8 · Live -- ends the new-design preview's
click-through flow. Same honesty as the real app's Trigger card: this
demo only ever shows the "live" state cosmetically, no real Exercise/
channel is created (that's real backend work, separate from this
design-review demo)."""

import logging

logger = logging.getLogger(__name__)


def build_training_mode_card(module: str, scenario: str) -> dict:
    """New first step before Trigger (flowchart's "Training mode?" box) --
    Yes sends a real pre-notification DM to every real team member who
    could be drilled, before Trigger now/Schedule/Surprise are even
    shown; No skips straight to Trigger, same as this screen always
    worked before this existed."""
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":zap: Step 7 · Trigger", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Training mode? (sends a heads-up DM to everyone on the team before the test starts)"}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes -- send pre-notification", "emoji": True}, "action_id": "v2_trigger_training_yes", "value": f"{module}:{scenario}", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No -- send test directly", "emoji": True}, "action_id": "v2_trigger_training_no", "value": f"{module}:{scenario}"},
                ],
            },
        ]
    }


def send_pre_notification(team_id: str, module: str, scenario: str, bot_token: str) -> int:
    """Real heads-up DM to every real person staffed on any team for this
    workspace -- same Team/TeamMember data exercises/drill.py's real
    fire_exercise() reads (read-only reuse, that file itself untouched).
    Returns how many people were actually reached."""
    from cards.models_v2 import Team, TeamMember
    from cards.slack_client import SlackApiError, _call

    sent_to = set()
    for team_doc in Team.objects(team_id=team_id):
        for tm in TeamMember.objects(team=team_doc):
            recipient = tm.primary_slack_user_ids[0] if tm.primary_slack_user_ids else ""
            if not recipient or recipient in sent_to:
                continue
            try:
                opened = _call("conversations.open", bot_token, users=recipient)
                dm_channel_id = opened["channel"]["id"]
                _call(
                    "chat.postMessage", bot_token, channel=dm_channel_id,
                    text=f":bell: Heads up -- a TestMyPlan drill ({scenario}) will run soon.",
                )
                sent_to.add(recipient)
            except SlackApiError:
                logger.exception("Trigger %s/%s: failed to send pre-notification to %s", module, scenario, recipient)
    return len(sent_to)


TRIGGERS = [
    ("now", "Trigger now", "Launch immediately — teams are notified in their channel"),
    ("sched", "Schedule", "Pick a window; participants get a calendar hold"),
    ("surprise", "Surprise window", "Fires at random within the next 7 days"),
]
TRIGGER_LABELS = dict((k, label) for k, label, _ in TRIGGERS)


def build_trigger_card(module: str, scenario: str, picked: str = "") -> dict:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":zap: Step 7 · Trigger", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": ":red_circle: *Required*"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Every test starts with a trigger.*"}},
        {"type": "divider"},
    ]
    for key, label, desc in TRIGGERS:
        is_picked = key == picked
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": (":white_check_mark: " if is_picked else "") + f"*{label}* — {desc}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Picked" if is_picked else "Choose", "emoji": True},
                    "action_id": f"v2_trigger_pick__{key}",
                    "value": f"{module}:{scenario}:{key}",
                    **({"style": "danger"} if key == "now" and not picked else {}),
                },
            }
        )

    # A scheduled/surprise drill is armed and waiting in the background --
    # let the admin actually cancel it instead of being stuck with no way
    # to undo a wrong date or an unwanted surprise window.
    if picked in ("sched", "surprise"):
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":x: Cancel", "emoji": True},
                        "action_id": "v2_trigger_cancel_scheduled",
                        "value": f"{module}:{scenario}",
                        "style": "danger",
                    }
                ],
            }
        )
    return {"blocks": blocks}


def build_live_card(module: str, scenario: str, trigger_key: str, exercise=None) -> dict:
    trigger_label = TRIGGER_LABELS.get(trigger_key, trigger_key)

    # Steps 1-6 are real now (Exercise + ExerciseTask + Done button +
    # backup escalation + report) -- this card was still showing its old
    # "not built yet" placeholder text even after all of that landed.
    # Scoring and timed injects genuinely aren't built yet, so those two
    # stay honest; "Participants notified" now reflects the real count.
    if exercise is not None:
        from exercises.models import ExerciseTask

        notified_count = ExerciseTask.objects(exercise=exercise).count()
        participants_text = f"{notified_count} real {'person' if notified_count == 1 else 'people'} DM'd" if notified_count else "Nobody was staffed on a team, so nobody was DM'd"
    else:
        participants_text = "_Not built yet — no real Exercise/channel behind this preview._"

    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": scenario, "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f":fire: *Live now*  ·  {trigger_label}"}]},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "The test is running in the war room. You can watch, inject complications, or pull the report at any time.",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Participants notified*\n{participants_text}"},
                    {"type": "mrkdwn", "text": "*Injects queued*\n0 — not built yet"},
                    {"type": "mrkdwn", "text": "*Scoring*\nNot built yet"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Preparedness report", "emoji": True},
                        "action_id": "v2_live_report",
                        "value": "report",
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
