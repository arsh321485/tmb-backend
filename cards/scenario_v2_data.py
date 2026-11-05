"""
Step 5 · Scenario -- shown after picking a cause on the Threat map.
Context (which threat/incident/cause) is carried through button values,
same as threat_map_v2_data.py, since this is pure navigation state, not
an accumulating form.
"""

from .threat_map_v2_data import _find_incident, _find_threat


def _team_label_for_role(role: str) -> str:
    """Which real team (T01, T02...) a role name belongs to, from the
    same catalog Teams & Roles itself is built from -- so a reviewer can
    see at a glance which team's member gets each question, same idea
    as Threat Profile's "Continue to Configure Test" labels."""
    from .team_catalog_v2 import ALL_TEAMS, ROLE_CATALOG_BY_TEAM

    for team_id, team_roles in ROLE_CATALOG_BY_TEAM.items():
        if any(r.get("role") == role for r in team_roles):
            team = next((t for t in ALL_TEAMS if t["id"] == team_id), None)
            if team:
                return f"{team_id} ({team['name']})"
            return team_id
    return ""


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
    actions_row = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": ":clipboard: View the test plan", "emoji": True},
            "action_id": "v2_scenario_done",
            "value": f"{module}:{selected}",
            **({"style": "primary"} if selected else {}),
        }
    ]
    if selected:
        # A22 -- writes a real scenario (injects + scored decisions) from
        # this org's own plan and assigned roles instead of the fixed
        # sample. Separate from "View the test plan" above, which still
        # shows the old fixed placeholder checklist for now.
        actions_row.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": ":sparkles: Generate real scenario with AI", "emoji": True},
                "action_id": "v2_scenario_generate",
                "value": f"{module}:{threat_id}:{incident_id}:{cause_id}",
            }
        )
    blocks.append({"type": "actions", "elements": actions_row})
    return {"blocks": blocks}


def build_generating_card(breadcrumb: str) -> dict:
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":hourglass_flowing_sand: Writing your scenario...", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "The AI is writing injects and decisions from your real plan and assigned roles. This can take a minute or two -- this message will update when it's ready.",
                },
            },
        ]
    }


def build_scenario_failed_card(breadcrumb: str, reason: str) -> dict:
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": ":warning: Couldn't generate a scenario", "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
            {"type": "section", "text": {"type": "mrkdwn", "text": reason}},
        ]
    }


def build_scenario_review_card(scenario_doc, breadcrumb: str) -> dict:
    """A23 -- the exercise lead reviews the AI's actual output before
    anything here can reach a real participant. No per-field editing yet
    (sir's call: see this working end to end first) -- Approve or discard
    and regenerate are the two real actions today."""
    status = scenario_doc.status

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":mag: Review AI-generated scenario", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{breadcrumb}_"}]},
    ]
    if status == "approved":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Approved* -- ready to be used in a real drill."}]})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Training mode? (sends a heads-up DM to everyone involved before the test starts)"},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes -- send pre-notification", "emoji": True}, "action_id": "v2_ai_training_yes", "value": str(scenario_doc.id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No -- send test directly", "emoji": True}, "action_id": "v2_ai_training_no", "value": str(scenario_doc.id)},
                ],
            }
        )
    blocks.append({"type": "divider"})

    for inj in scenario_doc.injects:
        role = inj.get("target_role", "?")
        team_label = _team_label_for_role(role)
        lines = [f"*{inj.get('seq', '?')}. {inj.get('title', 'Untitled')}* — _{inj.get('phase', '')}_"]
        lines.append(f"To: *{role}*" + (f"  ·  _{team_label}_" if team_label else ""))
        lines.append(inj.get("inject_message", ""))
        lines.append(f"\n*Decision:* {inj.get('decision_question', '')}")
        for opt in inj.get("options", []):
            lines.append(f"  • ({opt.get('rating', '?')}, {opt.get('score', '?')}/10) {opt.get('option_text', '')}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        blocks.append({"type": "divider"})

    if scenario_doc.consequence_injects:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Consequence injects (triggered by a Poor choice)*"}]})
        for inj in scenario_doc.consequence_injects:
            role = inj.get("target_role", "?")
            team_label = _team_label_for_role(role)
            to_text = f"To: {role}" + (f"  ·  _{team_label}_" if team_label else "")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{inj.get('title', 'Untitled')}* — {to_text}\n{inj.get('inject_message', '')}"},
                }
            )
        blocks.append({"type": "divider"})

    if status != "approved":
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve this scenario", "emoji": True},
                        "action_id": "v2_scenario_approve",
                        "value": str(scenario_doc.id),
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Discard and regenerate", "emoji": True},
                        "action_id": "v2_scenario_regenerate",
                        "value": str(scenario_doc.id),
                    },
                ],
            }
        )
    return {"blocks": blocks}
