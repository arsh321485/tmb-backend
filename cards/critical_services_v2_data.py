"""
Mission-Critical Process -> Primary Supporting Systems table -- a
"Critical Process" sub-tab on Upload & Analysis itself (sir's call: not
a separate nav tab, since it's built from the exact same BIA/BCP
extraction that tab already shows under RTO, just filtered/arranged
differently -- two views of one dataset belong on one screen, not two).
A "mission-critical process" here is every extracted item tagged
"Service"; its supporting systems are whichever Technology/Application
items the AI found named alongside it in the document
(plans/resilience_map.py's "supporting_systems" field).
"""


def critical_process_blocks(plan) -> list:
    services = (plan.resilience_map or {}).get("services") if plan else None
    if not services:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "_No BIA/BCP data yet._"}}]

    processes = [s for s in services if (s.get("category") or "Service") == "Service"]
    if not processes:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "_No mission-critical processes found in this document._"}}]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Every critical business process from this document, with whichever systems/applications it names as supporting it.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Mission-Critical Process*"},
                {"type": "mrkdwn", "text": "*Primary Supporting Systems*"},
            ],
        },
    ]
    for proc in processes:
        name = proc.get("name") or "Unnamed process"
        systems = proc.get("supporting_systems") or []
        systems_text = ", ".join(systems) if systems else "—"
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{name}*"},
                    {"type": "mrkdwn", "text": systems_text},
                ],
            }
        )
    return blocks
