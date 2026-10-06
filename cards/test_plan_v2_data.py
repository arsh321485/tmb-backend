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
                    "text": {"type": "plain_text", "text": ":zap: Arm this test", "emoji": True},
                    "action_id": "v2_plan_arm",
                    "value": f"{module}:{scenario}",
                    "style": "danger",
                }
            ],
        }
    )
    return {"blocks": blocks}
