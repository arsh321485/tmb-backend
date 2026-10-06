"""
Shared data + card-building for the new-design preview's "Threat map"
step (Step 4). Navigation state (which module/threat/incident is
expanded) is threaded straight through each button's value, same
pattern as the real app's threat map (cards/render.py) -- no block
parsing needed here since this is pure drill-down, not an accumulating
form.
"""

MODULES = ["Cybersecurity", "Privacy"]

TAXONOMY = {
    "Cybersecurity": [
        {
            "id": "ext", "label": "External attacker", "crit": "Critical",
            "incidents": [
                {
                    "id": "ransom", "name": "Ransomware outbreak",
                    "causes": [
                        {"id": "phish", "name": "Phishing email with weaponized attachment", "scenarios": ["Ransomware Containment", "Double-extortion with leak threat"]},
                        {"id": "rdp", "name": "Exposed RDP / VPN exploited", "scenarios": ["Domain-wide encryption via stolen creds"]},
                    ],
                },
                {
                    "id": "ato", "name": "Account takeover",
                    "causes": [
                        {"id": "stuff", "name": "Credential stuffing on cloud tenant", "scenarios": ["Cloud Account Takeover"]},
                        {"id": "mfa", "name": "MFA fatigue / push bombing", "scenarios": ["Privileged admin hijack"]},
                    ],
                },
            ],
        },
        {
            "id": "ins", "label": "Insider", "crit": "High",
            "incidents": [
                {
                    "id": "exfil", "name": "Data exfiltration",
                    "causes": [
                        {"id": "leaver", "name": "Departing employee mass-download", "scenarios": ["Insider Threat — Data Exfil"]},
                        {"id": "negli", "name": "Negligent sharing of sensitive files", "scenarios": ["Accidental public exposure"]},
                    ],
                },
            ],
        },
    ],
    "Privacy": [
        {
            "id": "breach", "label": "Personal-data breach", "crit": "Critical",
            "incidents": [
                {
                    "id": "disc", "name": "Unauthorized disclosure",
                    "causes": [
                        {"id": "device", "name": "Lost / stolen unencrypted device", "scenarios": ["Lost Device / PII Exposure"]},
                        {"id": "misconfig", "name": "Misconfigured access permissions", "scenarios": ["Public bucket of patient records"]},
                    ],
                },
                {
                    "id": "notif", "name": "Regulator-notifiable breach",
                    "causes": [
                        {"id": "vendor", "name": "Third-party processor compromised", "scenarios": ["GDPR Breach Notification (72h)", "Vendor Processor Breach"]},
                    ],
                },
            ],
        },
        {
            "id": "rights", "label": "Data-subject rights", "crit": "Med",
            "incidents": [
                {
                    "id": "overload", "name": "Rights-request overload",
                    "causes": [
                        {"id": "campaign", "name": "Coordinated SAR campaign", "scenarios": ["Subject Access Request Surge"]},
                    ],
                },
            ],
        },
    ],
}

# Cross-module "most critical now" shortcuts (module, threat_id).
CRITICAL_SHORTCUTS = [("Cybersecurity", "ext"), ("Privacy", "breach")]

CRIT_EMOJI = {"Critical": "🔴", "High": "🟠", "Med": "🟡"}


def _find_threat(module: str, threat_id: str) -> dict | None:
    return next((t for t in TAXONOMY.get(module, []) if t["id"] == threat_id), None)


def _find_incident(module: str, threat_id: str, incident_id: str) -> dict | None:
    threat = _find_threat(module, threat_id)
    if not threat:
        return None
    return next((i for i in threat["incidents"] if i["id"] == incident_id), None)


def build_threat_map_card(module: str = "Cybersecurity", expanded_threat: str = "", expanded_incident: str = "") -> dict:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":world_map: Step 4 · Threat map", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": ":red_circle: *Ranked by criticality*"}]},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "The threats you confirmed at setup, the incidents that exploit them, and each incident's causes. Pick a cause to see its test scenarios.",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": ":rotating_light: *Most critical now*"}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"{_find_threat(mod, tid)['label']} · {mod}", "emoji": True},
                    "action_id": f"v2_map_jump__{i}",
                    "value": f"{mod}:{tid}",
                }
                for i, (mod, tid) in enumerate(CRITICAL_SHORTCUTS)
            ],
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": m, "emoji": True},
                    "action_id": f"v2_map_module__{m}",
                    "value": m,
                    **({"style": "danger"} if m == module else {}),
                }
                for m in MODULES
            ],
        },
        {"type": "divider"},
    ]

    for threat in TAXONOMY.get(module, []):
        is_expanded = threat["id"] == expanded_threat
        emoji = CRIT_EMOJI.get(threat["crit"], "")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{threat['label']}*  ·  {len(threat['incidents'])} incident(s)  ·  {emoji} {threat['crit']}",
                },
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Hide incidents" if is_expanded else "Open incidents", "emoji": True},
                        "action_id": f"v2_map_expand_threat__{threat['id']}",
                        "value": f"{module}:{'' if is_expanded else threat['id']}",
                    }
                ],
            }
        )

        if is_expanded:
            for incident in threat["incidents"]:
                inc_expanded = incident["id"] == expanded_incident
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"› *{incident['name']}*  ·  {len(incident['causes'])} cause(s)"},
                    }
                )
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Hide causes" if inc_expanded else "View causes", "emoji": True},
                                "action_id": f"v2_map_expand_incident__{incident['id']}",
                                "value": f"{module}:{threat['id']}:{'' if inc_expanded else incident['id']}",
                            }
                        ],
                    }
                )
                if inc_expanded:
                    for cause in incident["causes"]:
                        blocks.append(
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": f"*{cause['name']}*"},
                            }
                        )
                        blocks.append(
                            {
                                "type": "actions",
                                "elements": [
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": f"Scenario — {sc[:30]} →", "emoji": True},
                                        "action_id": f"v2_map_pick_scenario__{cause['id']}__{si}",
                                        "value": f"{module}:{threat['id']}:{incident['id']}:{cause['id']}:{sc}",
                                        "style": "danger",
                                    }
                                    for si, sc in enumerate(cause["scenarios"])
                                ],
                            }
                        )
        blocks.append({"type": "divider"})

    return {"blocks": blocks}
