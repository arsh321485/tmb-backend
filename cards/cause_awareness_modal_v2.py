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
CAUSE_AWARENESS = {
    "phish": {
        "title": ":email: Phishing email",
        "body": "A fake email tricks someone into opening a malicious attachment or clicking a link. It's the #1 way ransomware gets in.\n\n*Why it matters:* anyone can be fooled by a well-written one, even trained staff -- it only takes one click.",
    },
    "rdp": {
        "title": ":closed_lock_with_key: Exposed remote access",
        "body": "A remote-login system (RDP/VPN) was left reachable from the internet with a weak or stolen password.\n\n*Why it matters:* attackers scan for these constantly -- it needs no trickery from anyone inside the company, just an unlocked door.",
    },
    "stuff": {
        "title": ":key: Credential stuffing",
        "body": "Attackers try passwords leaked from OTHER companies' breaches against your accounts, betting people reuse passwords.\n\n*Why it matters:* this works surprisingly often if multi-factor authentication isn't enforced everywhere.",
    },
    "mfa": {
        "title": ":bell: MFA fatigue",
        "body": "An attacker who already has a stolen password spams the victim with login-approval requests until they tap \"Approve\" just to make it stop.\n\n*Why it matters:* it's a real, common way MFA gets bypassed -- the victim approves it themselves.",
    },
    "leaver": {
        "title": ":outbox_tray: Departing employee",
        "body": "Someone leaving the company downloads large amounts of data before their access is cut off.\n\n*Why it matters:* often not malicious intent at first, but a real data-loss risk if access isn't revoked fast enough.",
    },
    "negli": {
        "title": ":open_file_folder: Accidental sharing",
        "body": "Sensitive files get shared more broadly than intended -- wrong recipient, a public link, a misconfigured folder.\n\n*Why it matters:* no attacker is needed at all, just a mistake.",
    },
    "device": {
        "title": ":iphone: Lost or stolen device",
        "body": "A laptop or phone with sensitive data goes missing.\n\n*Why it matters:* if it isn't encrypted, whoever finds it can read everything on it.",
    },
    "misconfig": {
        "title": ":warning: Misconfigured access",
        "body": "A system was set up to allow more access than it should -- e.g. a public cloud storage bucket.\n\n*Why it matters:* the data was never \"hacked\" -- it was just left open for anyone to find.",
    },
    "vendor": {
        "title": ":handshake: Third-party compromise",
        "body": "A vendor or partner who holds or processes your data gets breached.\n\n*Why it matters:* your data is exposed even though your own systems were never touched.",
    },
    "campaign": {
        "title": ":busts_in_silhouette: Coordinated request campaign",
        "body": "Many people submit data-access/deletion requests at once, sometimes orchestrated.\n\n*Why it matters:* it can overwhelm the team's ability to respond within the legal deadline.",
    },
}


def build_modal_view(cause_id: str) -> dict:
    info = CAUSE_AWARENESS.get(cause_id)
    blocks = (
        [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{info['title']}*"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": info["body"]}},
        ]
        if info
        else [{"type": "section", "text": {"type": "mrkdwn", "text": "No awareness note for this cause yet."}}]
    )
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Awareness"},
        "close": {"type": "plain_text", "text": "Got it"},
        "blocks": blocks,
    }


def open_modal(trigger_id: str, cause_id: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(cause_id)},
        timeout=10,
    )
