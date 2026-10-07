"""Step 6 · Test plan -- the phased checklist for the chosen scenario."""

PHASES = {
    "Cybersecurity": [
        {"name": "Threat confirmed & triage", "steps": ["Validate the first alert against the threat", "Confirm the incident type and severity", "Open the war room and assign roles"]},
        {"name": "Containment", "steps": ["Make the containment decision on the bridge", "Execute and confirm the action", "Preserve forensic evidence before cleanup"]},
        {"name": "Cause & spread", "steps": ["Trace the cause back to patient zero", "Check who else the cause reached", "Close the entry point"]},
        {"name": "Notification", "steps": ["Brief legal, privacy and leadership", "Prepare external holding lines"]},
        {"name": "Recovery & review", "steps": ["Restore affected systems and validate", "Measure detection and containment times", "Log evidence for the hot-wash"]},
    ],
    "default": [
        {"name": "Trigger & triage", "steps": ["Validate the first alert", "Declare severity and open the bridge", "Assign roles from the response team"]},
        {"name": "Containment", "steps": ["Make the containment decision", "Execute and confirm the action"]},
        {"name": "Notification", "steps": ["Brief legal and leadership", "Prepare external holding lines"]},
        {"name": "Recovery & review", "steps": ["Restore and validate", "Log evidence for the hot-wash"]},
    ],
}


def build_real_test_plan_card(plan_id: str, active_phase: str, active_scenario: str) -> dict:
    """Real plan content (sir's spreadsheet), reached via the Threat Profile
    card's new Phase/Scenario tabs + Trigger button."""
    from .plan_catalog_v2 import PLAN_META, phases_for_plan, steps_for_phase

    meta = PLAN_META.get(plan_id, {})
    phases = phases_for_plan(plan_id)
    total_steps = sum(len(steps_for_phase(plan_id, p)) for p in phases)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Test plan", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":red_circle: *{total_steps} steps* · Plan {plan_id}"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{meta.get('incident', '')}*\n_{meta.get('cause', '')}_"}},
        {"type": "divider"},
    ]

    icons = ["one", "two", "three", "four", "five", "six"]
    for i, phase in enumerate(phases, 1):
        steps = steps_for_phase(plan_id, phase)
        is_active = phase == active_phase
        lines = []
        for s in steps:
            marker = "▸" if is_active and s["scenario"] == active_scenario else "•"
            lines.append(f"{marker} *{s['scenario']}* — {s['teams']} ({s['roles']})")
        step_lines = "\n".join(lines)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":{icons[i - 1]}: *{phase}*{'  _(current)_' if is_active else ''}\n{step_lines}"},
            }
        )
        blocks.append({"type": "divider"})

    current_step = next((s for s in steps_for_phase(plan_id, active_phase) if s["scenario"] == active_scenario), None)
    if current_step:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":large_blue_circle: *Current step:* {current_step['scenario']}\n{current_step['task']}"},
            }
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":rocket: Launch test", "emoji": True},
                    "action_id": "v2_plan_arm_real",
                    "value": f"{plan_id}:{active_phase}:{active_scenario}",
                    "style": "danger",
                }
            ],
        }
    )
    return {"blocks": blocks}


def build_test_plan_card(module: str, scenario: str) -> dict:
    phases = PHASES.get(module, PHASES["default"])
    total_steps = sum(len(p["steps"]) for p in phases)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Test plan", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":red_circle: *{total_steps} steps*"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{scenario}*"}},
        {"type": "divider"},
    ]

    for i, phase in enumerate(phases, 1):
        step_lines = "\n".join(f"• {s}" for s in phase["steps"])
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":{['one','two','three','four','five','six'][i-1]}: *{phase['name']}*\n{step_lines}"},
            }
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":rocket: Launch test", "emoji": True},
                    "action_id": "v2_plan_arm",
                    "value": f"{module}:{scenario}",
                    "style": "danger",
                }
            ],
        }
    )
    return {"blocks": blocks}
