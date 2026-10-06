"""
"Inject a scenario" on the new-design preview's Live card opens this
modal -- the closest real equivalent to the mockup's bottom sheet
(Slack has no floating panel, a modal is the real analog). Clicking
"Send" on any row posts a real message into the channel and closes the
modal -- there's no real live-exercise engine behind this yet (that's
separate backend work, D1-D14 on the tracker), so this only records
that an inject was picked, same honesty as the real app's version.
"""

import requests

SLACK_API_BASE = "https://slack.com/api"

INJECTS = [
    {"title": "Second wave", "sev": "High", "text": "A second cause surfaces — the same credentials were used against the VPN an hour before the phishing click."},
    {"title": "Media inquiry", "sev": "Med", "text": "A journalist emails the press office asking about 'a systems outage at Veridian.'"},
    {"title": "Executive pressure", "sev": "Med", "text": "The COO asks for a firm recovery ETA to share with the board."},
]
SEV_EMOJI = {"High": "🟠", "Med": "🟡"}


def build_modal_view(channel_id: str) -> dict:
    blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": ":fire: *Turn up the heat*"}]},
    ]
    for i, inj in enumerate(INJECTS):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{SEV_EMOJI.get(inj['sev'], '')} *{inj['title']}*  ·  `{inj['sev']}`\n{inj['text']}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Send", "emoji": True},
                    "action_id": f"v2_inject_send__{i}",
                    "value": str(i),
                },
            }
        )
        blocks.append({"type": "divider"})

    return {
        "type": "modal",
        "callback_id": "v2_inject_modal",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Inject a scenario"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }


def open_modal(trigger_id: str, channel_id: str, bot_token: str) -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(channel_id)},
        timeout=10,
    )


def send_inject(index: int, channel_id: str, view_id: str, bot_token: str) -> None:
    if not (0 <= index < len(INJECTS)):
        return
    inj = INJECTS[index]
    requests.post(
        f"{SLACK_API_BASE}/chat.postMessage",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "text": f":zap: Injected: *{inj['title']}* (`{inj['sev']}`) — {inj['text']}"},
        timeout=10,
    )
    requests.post(
        f"{SLACK_API_BASE}/views.close",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"view_id": view_id},
        timeout=10,
    )
