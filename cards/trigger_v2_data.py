"""Shared Trigger-type catalog -- reused by the AI scenario drill's own
Trigger screens (cards/ai_drill_v2.py). The old hand-written plan drill
that used to live in this file (build_training_mode_card, build_trigger_card,
build_live_card, send_pre_notification) is removed entirely -- only the
AI-generated scenario drill is used now."""

TRIGGERS = [
    ("now", ":rotating_light:", "Trigger now", "Launch immediately — teams are notified in their channel"),
    ("sched", ":calendar:", "Schedule", "Pick a window; participants get a calendar hold"),
    ("surprise", ":game_die:", "Surprise window", "Fires at random within the next 7 days"),
]
TRIGGER_LABELS = dict((k, label) for k, _, label, _ in TRIGGERS)
