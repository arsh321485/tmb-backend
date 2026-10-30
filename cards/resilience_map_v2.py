"""
Phase 1 (Read) -- A10: the real review card for what the NVIDIA model
extracted from an uploaded plan (plans/resilience_map.py). Posted into
the same DM right after a plan upload finishes, so the Plans & BIA
owner can actually see and confirm the resilience map, instead of it
only existing in the database.
"""

import logging

import requests

SLACK_API_BASE = "https://slack.com/api"
logger = logging.getLogger(__name__)

# Slack's real hard limit is 50 blocks per message -- a few under that as
# safety margin. Confirmed live: a real 16-service plan (with roles,
# response teams, alternate sites and key contacts) built 53 blocks, which
# Slack rejected outright ("invalid_blocks"). The old code never checked
# chat.postMessage's response for "ok": false, so that failure was
# completely silent -- the plan was saved and extracted fine, but no card
# (and no error) ever appeared.
_MAX_BLOCKS_PER_MESSAGE = 48


def _chunk_blocks(blocks: list, size: int) -> list:
    return [blocks[i : i + size] for i in range(0, len(blocks), size)]


def _post_json(payload: dict, bot_token: str, *, endpoint: str = "chat.postMessage") -> bool:
    """POSTs to the given Slack method and actually checks the response
    for "ok": false (an HTTP 200 with a Slack-side error, e.g.
    invalid_blocks, rate_limited) -- not just network failures. Returns
    True on success so callers can react to a real failure instead of
    assuming it worked."""
    try:
        resp = requests.post(
            f"{SLACK_API_BASE}/{endpoint}",
            headers={"Authorization": f"Bearer {bot_token}"},
            json=payload,
            timeout=10,
        )
        data = resp.json()
    except requests.RequestException:
        logger.exception("Slack %s request failed", endpoint)
        return False
    except ValueError:
        logger.error("Slack %s returned a non-JSON response: %s", endpoint, resp.text[:300])
        return False

    if not data.get("ok"):
        logger.error(
            "Slack %s failed: %s -- channel=%s blocks=%s",
            endpoint,
            data.get("error"),
            payload.get("channel"),
            len(payload.get("blocks", [])),
        )
        return False
    return True


def build_card(plan) -> dict:
    resilience_map = plan.resilience_map or {}
    services = resilience_map.get("services", [])
    notifications = resilience_map.get("notification_commitments", [])
    roles = resilience_map.get("roles", [])
    document_date = resilience_map.get("document_date", "")
    status = plan.resilience_map_status or "proposed"

    badge = ":white_check_mark: Approved" if status == "approved" else ":large_yellow_circle: Proposed -- needs review"

    context_text = f"From *{plan.filename}*  ·  {badge}"
    if document_date:
        context_text += f"  ·  Document dated: {document_date}"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":bar_chart: Resilience map", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context_text}]},
    ]

    if not services:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No services could be extracted from this document._"}})
    else:
        for svc in services:
            lines = [f"*{svc.get('name', 'Unnamed service')}*"]
            if svc.get("owner"):
                lines.append(f"Owner: {svc['owner']}")
            targets = []
            if svc.get("rto"):
                targets.append(f"RTO {svc['rto']}")
            if svc.get("rpo"):
                targets.append(f"RPO {svc['rpo']}")
            if targets:
                lines.append(" · ".join(targets))
            if svc.get("minimum_service_level"):
                lines.append(f"Minimum service level: {svc['minimum_service_level']}")
            if svc.get("dependencies"):
                lines.append(f"Depends on: {', '.join(svc['dependencies'])}")
            if svc.get("impact_if_disrupted"):
                lines.append(f"Impact if disrupted: {svc['impact_if_disrupted']}")
            if svc.get("source"):
                lines.append(f"_“{svc['source']}”_")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
            blocks.append({"type": "divider"})

    if notifications:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Notification commitments*"}]})
        lines = [f"• {n.get('who', '?')} -- within {n.get('deadline', '?')}" for n in notifications]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        blocks.append({"type": "divider"})

    if roles:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Roles and backups*"}]})
        lines = []
        for r in roles:
            title = r.get("title", "Unnamed role")
            person = r.get("person", "")
            who = f"{title} ({person})" if person and person.upper() != "N/A" else title
            backup_note = ":white_check_mark: backup named" if r.get("has_backup") else ":warning: no backup named"
            lines.append(f"• {who} -- {backup_note}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        blocks.append({"type": "divider"})

    response_teams = resilience_map.get("response_teams", [])
    if response_teams:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Response teams*"}]})
        lines = []
        for t in response_teams:
            name = t.get("name", "Unnamed team")
            members = t.get("members") or []
            members_str = f" -- {', '.join(members)}" if members else ""
            lines.append(f"• {name}{members_str}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        blocks.append({"type": "divider"})

    key_contacts = resilience_map.get("key_contacts", [])
    if key_contacts:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Key contacts*"}]})
        lines = []
        for c in key_contacts:
            name = c.get("name", "Unnamed contact")
            role = c.get("role", "")
            details = c.get("details", "")
            bits = [b for b in [role, details] if b]
            suffix = f" -- {' · '.join(bits)}" if bits else ""
            lines.append(f"• {name}{suffix}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        blocks.append({"type": "divider"})

    if status != "approved" and services:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Confirm this resilience map", "emoji": True},
                        "action_id": "resmap_confirm",
                        "value": str(plan.id),
                        "style": "primary",
                    }
                ],
            }
        )
    elif status == "approved":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Confirmed -- these are the real recovery targets this plan will be scored against."}]})

    return {"blocks": blocks}


def build_gaps_card(plan) -> dict:
    """A11 -- issues find_resilience_gaps() flagged, one Accept button
    per gap. Not shown at all if there's nothing to flag."""
    from plans.resilience_gaps import find_resilience_gaps, other_resilience_maps_for_team

    other_plans = other_resilience_maps_for_team(plan.slack_team_id, exclude_plan_id=plan.id)
    gaps = find_resilience_gaps(plan.resilience_map or {}, other_plans=other_plans)
    accepted = set(plan.accepted_gaps or [])

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":mag: Gaps to review", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"From *{plan.filename}* -- before the recovery targets can be locked in, review what's missing or unclear."}]},
    ]

    all_keys = {f"{g['service']}|{g['issue']}" for g in gaps}
    remaining_now = len(all_keys - accepted)
    if remaining_now > 1:
        # A real plan with many services can flag dozens of gaps, one
        # Accept button each -- too many for a human to click through one
        # at a time. "Accept all" is a deliberate bulk shortcut for the
        # common case (e.g. "no dependencies listed" on every service),
        # not a replacement for reviewing anything that actually needs a
        # real decision -- the owner can still accept individually instead.
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": f"Accept all {remaining_now} remaining", "emoji": True},
                        "action_id": "resmap_gap_accept_all",
                        "value": str(plan.id),
                    }
                ],
            }
        )
        blocks.append({"type": "divider"})

    for gap in gaps:
        key = f"{gap['service']}|{gap['issue']}"
        is_accepted = key in accepted
        text = f"*{gap['service']}*\n{gap['issue']}"
        section = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        if is_accepted:
            section["accessory"] = {"type": "button", "text": {"type": "plain_text", "text": "✓ Accepted", "emoji": True}, "action_id": "resmap_gap_noop", "value": "noop"}
        else:
            section["accessory"] = {
                "type": "button",
                "text": {"type": "plain_text", "text": "Accept", "emoji": True},
                "action_id": "resmap_gap_accept",
                "value": f"{plan.id}|{key}",
            }
        blocks.append(section)

    blocks.append({"type": "divider"})
    remaining = len(all_keys - accepted)
    if remaining == 0:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "All gaps reviewed -- the objectives register can now be locked in below."}]})
    else:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"{remaining} gap(s) still need review."}]})

    return {"blocks": blocks}


def build_objectives_card(plan) -> dict:
    """A12 -- the final, clean recovery-objectives register for the
    Plans & BIA owner to lock in, separate from A10's general map
    confirmation."""
    services = (plan.resilience_map or {}).get("services", [])
    status = plan.objectives_register_status or ""

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":lock: Recovery objectives register", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"From *{plan.filename}* -- this is the real scoring baseline every future drill is measured against."}]},
    ]

    for svc in services:
        targets = []
        if svc.get("rto"):
            targets.append(f"RTO {svc['rto']}")
        if svc.get("rpo"):
            targets.append(f"RPO {svc['rpo']}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{svc.get('name', 'Unnamed service')}*\n{' · '.join(targets) if targets else '_No targets found_'}"},
            }
        )

    blocks.append({"type": "divider"})
    if status == "approved":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Locked in -- this is the final objectives register."}]})
    else:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "\U0001F512 Lock in objectives register", "emoji": True},
                        "action_id": "resmap_objectives_lock",
                        "value": str(plan.id),
                        "style": "primary",
                    }
                ],
            }
        )

    return {"blocks": blocks}


def send_card(plan, channel_id: str, bot_token: str) -> None:
    if not (channel_id and bot_token):
        return
    blocks = build_card(plan)["blocks"]

    if len(blocks) <= _MAX_BLOCKS_PER_MESSAGE:
        _post_json({"channel": channel_id, "text": "Resilience map ready for review", "blocks": blocks}, bot_token)
        return

    # A long real plan can legitimately need more than one Slack message's
    # worth of blocks (confirmed live) -- split rather than drop data or
    # fail silently. The "Confirm" button is the last block built, so it
    # naturally lands in the final chunk.
    for i, chunk in enumerate(_chunk_blocks(blocks, _MAX_BLOCKS_PER_MESSAGE)):
        text = "Resilience map ready for review" if i == 0 else "Resilience map (continued)"
        _post_json({"channel": channel_id, "text": text, "blocks": chunk}, bot_token)


def update_card(plan, channel_id: str, message_ts: str, bot_token: str) -> None:
    if not (channel_id and message_ts and bot_token):
        return
    blocks = build_card(plan)["blocks"]
    if len(blocks) > _MAX_BLOCKS_PER_MESSAGE:
        # chat.update can only replace the one original message, so a plan
        # big enough to need multiple messages on first send can't be
        # losslessly re-rendered into a single update -- log clearly
        # rather than silently failing again, and skip the update (the
        # full content from send_card's multi-message post is still
        # there; only the status badge line wouldn't refresh).
        logger.warning(
            "Skipping resilience map card update for plan %s -- %s blocks exceeds Slack's per-message limit",
            plan.id,
            len(blocks),
        )
        return
    _post_json({"channel": channel_id, "ts": message_ts, "blocks": blocks}, bot_token, endpoint="chat.update")


def _post(channel_id: str, bot_token: str, text: str, card: dict) -> None:
    if not (channel_id and bot_token):
        return
    _post_json({"channel": channel_id, "text": text, **card}, bot_token)


def _update(channel_id: str, message_ts: str, bot_token: str, card: dict) -> None:
    if not (channel_id and message_ts and bot_token):
        return
    _post_json({"channel": channel_id, "ts": message_ts, **card}, bot_token, endpoint="chat.update")


def send_gaps_card(plan, channel_id: str, bot_token: str) -> None:
    if not (channel_id and bot_token):
        return
    blocks = build_gaps_card(plan)["blocks"]
    if len(blocks) <= _MAX_BLOCKS_PER_MESSAGE:
        _post_json({"channel": channel_id, "text": "Gaps to review", "blocks": blocks}, bot_token)
        return
    # Same real failure mode as the resilience map card -- a plan with
    # enough services can flag more gaps than fit in one message.
    for i, chunk in enumerate(_chunk_blocks(blocks, _MAX_BLOCKS_PER_MESSAGE)):
        text = "Gaps to review" if i == 0 else "Gaps to review (continued)"
        _post_json({"channel": channel_id, "text": text, "blocks": chunk}, bot_token)


def update_gaps_card(plan, channel_id: str, message_ts: str, bot_token: str) -> None:
    if not (channel_id and message_ts and bot_token):
        return
    blocks = build_gaps_card(plan)["blocks"]
    if len(blocks) > _MAX_BLOCKS_PER_MESSAGE:
        logger.warning(
            "Skipping gaps card update for plan %s -- %s blocks exceeds Slack's per-message limit",
            plan.id,
            len(blocks),
        )
        return
    _post_json({"channel": channel_id, "ts": message_ts, "blocks": blocks}, bot_token, endpoint="chat.update")


def send_objectives_card(plan, channel_id: str, bot_token: str) -> None:
    _post(channel_id, bot_token, "Recovery objectives register", build_objectives_card(plan))


def update_objectives_card(plan, channel_id: str, message_ts: str, bot_token: str) -> None:
    _update(channel_id, message_ts, bot_token, build_objectives_card(plan))


def build_retry_card(plan, version_note: str = "") -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":inbox_tray: Got it -- *{plan.filename}* uploaded and parsed.{version_note} "
                    ":warning: Couldn't generate a resilience map this time -- the AI step timed out. The file is still saved.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "\U0001F504 Retry AI extraction", "emoji": True},
                        "action_id": "resmap_retry",
                        "value": str(plan.id),
                        "style": "primary",
                    }
                ],
            },
        ]
    }


def send_retry_card(plan, channel_id: str, bot_token: str, version_note: str = "") -> None:
    _post(channel_id, bot_token, "Couldn't generate a resilience map", build_retry_card(plan, version_note))


def update_retry_card(plan, channel_id: str, message_ts: str, bot_token: str) -> None:
    _update(channel_id, message_ts, bot_token, build_retry_card(plan))
