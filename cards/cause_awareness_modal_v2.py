"""
A real popup (sir's call -- not text stuffed into Step 6) that opens
the instant someone clicks a Cause tab, explaining in plain language
what that cause actually is and why it matters. Same spirit as the
"why" text Threat Profile already shows per threat, just surfaced as
its own card instead of inline.

No submission needed -- this is read-only, so the modal has no
"submit", just a "close" button. Opened from
cards.interactivity_v2's handler for v2_cfgtest_cause_tab__, using the
click's own trigger_id, alongside (not instead of) redrawing Step 6.
"""

import requests

SLACK_API_BASE = "https://slack.com/api"

# Keyed by the real cause ids in cards/threat_map_v2_data.py's taxonomy.
# "what" and "why" are kept separate (not one blob of text) so the
# modal can style "why it matters" as its own visually distinct callout
# instead of just another paragraph.
CAUSE_AWARENESS = {
    "phish": {
        "icon": ":email:",
        "title": "Phishing email",
        "what": "A fake email tricks someone into opening a malicious attachment or clicking a link. It's the #1 way ransomware gets in.",
        "why": "Anyone can be fooled by a well-written one, even trained staff — it only takes one click.",
    },
    "rdp": {
        "icon": ":closed_lock_with_key:",
        "title": "Exposed remote access",
        "what": "A remote-login system (RDP/VPN) was left reachable from the internet with a weak or stolen password.",
        "why": "Attackers scan for these constantly — it needs no trickery from anyone inside the company, just an unlocked door.",
    },
    "stuff": {
        "icon": ":key:",
        "title": "Credential stuffing",
        "what": "Attackers try passwords leaked from OTHER companies' breaches against your accounts, betting people reuse passwords.",
        "why": "This works surprisingly often if multi-factor authentication isn't enforced everywhere.",
    },
    "mfa": {
        "icon": ":bell:",
        "title": "MFA fatigue",
        "what": "An attacker who already has a stolen password spams the victim with login-approval requests until they tap \"Approve\" just to make it stop.",
        "why": "A real, common bypass for MFA — the victim approves it themselves without realizing.",
    },
    "leaver": {
        "icon": ":outbox_tray:",
        "title": "Departing employee",
        "what": "Someone leaving the company downloads large amounts of data before their access is cut off.",
        "why": "Often not malicious intent at first, but a real data-loss risk if access isn't revoked fast enough.",
    },
    "negli": {
        "icon": ":open_file_folder:",
        "title": "Accidental sharing",
        "what": "Sensitive files get shared more broadly than intended — wrong recipient, a public link, a misconfigured folder.",
        "why": "No attacker is needed at all, just a mistake.",
    },
    "device": {
        "icon": ":iphone:",
        "title": "Lost or stolen device",
        "what": "A laptop or phone with sensitive data goes missing.",
        "why": "If it isn't encrypted, whoever finds it can read everything on it.",
    },
    "misconfig": {
        "icon": ":warning:",
        "title": "Misconfigured access",
        "what": "A system was set up to allow more access than it should — e.g. a public cloud storage bucket.",
        "why": "The data was never \"hacked\" — it was just left open for anyone to find.",
    },
    "vendor": {
        "icon": ":handshake:",
        "title": "Third-party compromise",
        "what": "A vendor or partner who holds or processes your data gets breached.",
        "why": "Your data is exposed even though your own systems were never touched.",
    },
    "campaign": {
        "icon": ":busts_in_silhouette:",
        "title": "Coordinated request campaign",
        "what": "Many people submit data-access/deletion requests at once, sometimes orchestrated.",
        "why": "It can overwhelm the team's ability to respond within the legal deadline.",
    },
}


# Picks a header icon for a dynamically-generated (Agent 1.5) cause by
# keyword, same spirit as each hand-picked icon in CAUSE_AWARENESS above
# -- checked in order, first match wins, so a cause mentioning several
# keywords still gets one deliberate icon instead of a random pick.
_ICON_KEYWORDS = (
    (("phish", "email", "link"), ":email:"),
    (("api", "key", "token", "credential", "password", "secret"), ":key:"),
    (("rdp", "vpn", "remote", "access", "login"), ":closed_lock_with_key:"),
    (("mfa", "authentication", "2fa"), ":bell:"),
    (("vendor", "third-party", "third party", "supplier", "partner"), ":handshake:"),
    (("device", "laptop", "phone", "mobile"), ":iphone:"),
    (("misconfig", "config", "permission", "scope", "bucket"), ":warning:"),
    (("insider", "employee", "staff", "leaver"), ":bust_in_silhouette:"),
    (("data", "exfilt", "leak", "share"), ":open_file_folder:"),
)


def _icon_for(cause_name: str) -> str:
    haystack = cause_name.lower()
    for keywords, icon in _ICON_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return icon
    return ":rotating_light:"


_CRIT_BADGE = {
    "Critical": "🟫 Critical",
    "High": "🟥 High",
    "Med": "🟨 Medium",
}


def build_modal_view(
    cause_id: str, cause_name: str = "", incident_name: str = "", what: str = "", why: str = "",
    module: str = "", crit: str = "",
) -> dict:
    info = CAUSE_AWARENESS.get(cause_id)
    if not info:
        # Most causes today are AI-generated (Agent 1.5), so their ids
        # are never in the fixed CAUSE_AWARENESS dict above. Agent 1.5
        # now writes its own "what"/"why" per cause (same shape as the
        # fixed dict), cached alongside the cause -- styled as a real
        # awareness card: icon header, a module/severity badge row,
        # a quick-facts strip, then the two labeled callouts and a
        # closing tip, instead of the plain stacked sections this
        # used to be.
        if not cause_name:
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": ":grey_question: No awareness note for this cause yet."}}]
            return {"type": "modal", "title": {"type": "plain_text", "text": "Awareness"}, "close": {"type": "plain_text", "text": "Close"}, "blocks": blocks}

        blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"{_icon_for(cause_name)}  {cause_name}", "emoji": True}}]

        badge_bits = []
        if module:
            badge_bits.append(f":label: {module}")
        if crit and crit in _CRIT_BADGE:
            badge_bits.append(_CRIT_BADGE[crit])
        if badge_bits:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "   |   ".join(badge_bits)}]})

        if incident_name:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":round_pushpin: *Root cause behind:*  {incident_name}"},
                }
            )
        blocks.append({"type": "divider"})
        if what:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":books:  *WHAT THIS IS*\n{what}"}})
            blocks.append({"type": "divider"})
        if why:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":rotating_light:  *WHY IT MATTERS*\n> {why}"}})
            blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":bulb: *Knowing this helps your team recognise and react faster during a real test.*"},
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":hourglass_flowing_sand: Setting up the scenario for this cause now — it'll be ready on the screen behind this in a few seconds."}],
            }
        )
        return {"type": "modal", "title": {"type": "plain_text", "text": "Awareness"}, "close": {"type": "plain_text", "text": "Got it", "emoji": True}, "blocks": blocks}

    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"{info['icon']}  {info['title']}", "emoji": True}}]
    badge_bits = []
    if module:
        badge_bits.append(f":label: {module}")
    if crit and crit in _CRIT_BADGE:
        badge_bits.append(_CRIT_BADGE[crit])
    if badge_bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "   |   ".join(badge_bits)}]})
    blocks += [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":books:  *WHAT THIS IS*\n{info['what']}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":rotating_light:  *WHY IT MATTERS*\n> {info['why']}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": ":bulb: *Knowing this helps your team recognise and react faster during a real test.*"}},
    ]
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Awareness"},
        "close": {"type": "plain_text", "text": "Got it", "emoji": True},
        "blocks": blocks,
    }


def open_modal(
    trigger_id: str, cause_id: str, bot_token: str, cause_name: str = "", incident_name: str = "",
    what: str = "", why: str = "", module: str = "", crit: str = "",
) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={
            "trigger_id": trigger_id,
            "view": build_modal_view(
                cause_id, cause_name=cause_name, incident_name=incident_name, what=what, why=why, module=module, crit=crit,
            ),
        },
        timeout=10,
    )
