"""Step 7 · Trigger, and Step 8 · Live -- ends the new-design preview's
click-through flow. Same honesty as the real app's Trigger card: this
demo only ever shows the "live" state cosmetically, no real Exercise/
channel is created (that's real backend work, separate from this
design-review demo)."""

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
