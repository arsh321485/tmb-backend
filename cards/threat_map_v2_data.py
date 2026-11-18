"""
The old fixed demo taxonomy (ransomware/phishing/etc.) this app shipped
with before the real AI threat pipeline existed. The "Threat Mapping"
tab a real admin sees today is threats_v2_data.py's real org-threats
screen (nav key "org_threats") -- this file's own card (build_threat_map_card,
reached via the now-orphaned "threat_map" nav key) was removed entirely
since nothing in the live nav bar points to it any more.

TAXONOMY/_find_threat are kept ONLY as a fallback lookup used elsewhere
(resolve_names and friends) for a handful of hand-authored threats that
predate Agent 1 -- a real AI-generated threat never matches here and
falls through to the real ensure_threat_map cache instead.
"""

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


def _find_threat(module: str, threat_id: str) -> dict | None:
    return next((t for t in TAXONOMY.get(module, []) if t["id"] == threat_id), None)

