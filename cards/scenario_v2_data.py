"""
Step 5 · Scenario -- shown after picking a cause on the Threat map.
Context (which threat/incident/cause) is carried through button values,
same as threat_map_v2_data.py, since this is pure navigation state, not
an accumulating form.
"""

from .threat_map_v2_data import _find_incident, _find_threat


def _breadcrumb(module: str, threat_id: str, incident_id: str, cause_id: str) -> str:
    threat = _find_threat(module, threat_id)
    incident = _find_incident(module, threat_id, incident_id)
    cause = next((c for c in (incident or {}).get("causes", []) if c["id"] == cause_id), None) if incident else None
    parts = [p for p in [threat and threat["label"], incident and incident["name"], cause and cause["name"]] if p]
    return "  ›  ".join(parts)


def _cause_scenarios(module: str, threat_id: str, incident_id: str, cause_id: str) -> list:
    incident = _find_incident(module, threat_id, incident_id)
    if not incident:
        return []
    cause = next((c for c in incident["causes"] if c["id"] == cause_id), None)
    return cause["scenarios"] if cause else []


def build_scenario_card(module: str, threat_id: str, incident_id: str, cause_id: str, selected: str = "") -> dict:
    scenarios = _cause_scenarios(module, threat_id, incident_id, cause_id)
    breadcrumb = _breadcrumb(module, threat_id, incident_id, cause_id)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":dart: Step 5 · Scenario", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"`{module}`"}]},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
        {"type": "divider"},
    ]

    for i, sc in enumerate(scenarios):
        is_selected = sc == selected
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": (":white_check_mark: " if is_selected else ":radio_button: ") + f"*{sc}*"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Selected" if is_selected else "Select", "emoji": True},
                    "action_id": f"v2_scenario_pick__{i}",
                    "value": f"{module}:{threat_id}:{incident_id}:{cause_id}:{sc}",
                    **({"style": "danger"} if is_selected else {}),
                },
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":clipboard: View the test plan", "emoji": True},
                    "action_id": "v2_scenario_done",
                    "value": f"{module}:{selected}",
                    **({"style": "primary"} if selected else {}),
                }
            ],
        }
    )
    return {"blocks": blocks}
