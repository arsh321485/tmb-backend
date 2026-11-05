"""
"Upload" button for the new wizard's BIA/BCP step -- a real file picker
modal instead of telling the admin to go DM the file separately. Still
feeds the exact same, proven ingestion pipeline (plans/intake.py's
ingest_one_file, unmodified) once a file comes back from the modal, so
nothing about how a plan actually gets parsed changes.
"""

import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
CALLBACK_ID = "v2_bia_upload_modal"


def build_modal_view(channel_id: str = "", message_ts: str = "") -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": json.dumps({"channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Upload BIA / BCP"},
        "submit": {"type": "plain_text", "text": "Upload"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "file_block",
                "label": {"type": "plain_text", "text": "BIA or BCP document"},
                "element": {
                    "type": "file_input",
                    "action_id": "file",
                    "filetypes": ["docx", "pdf", "xlsx"],
                    "max_files": 1,
                },
            },
        ],
    }


def open_modal(trigger_id: str, channel_id: str, bot_token: str, message_ts: str = "") -> None:
    requests.post(
        f"{SLACK_API_BASE}/views.open",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"trigger_id": trigger_id, "view": build_modal_view(channel_id, message_ts)},
        timeout=10,
    )


def _warn(channel_id: str, bot_token: str, text: str) -> None:
    if not (channel_id and bot_token):
        logger.warning("BIA upload modal: %s (no channel to post to)", text)
        return
    try:
        requests.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel_id, "text": f":warning: {text}"},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Couldn't post upload warning: %s", text)


def handle_submission(payload: dict, bot_token: str) -> None:
    from plans.intake import ingest_one_file

    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except json.JSONDecodeError:
        meta = {}
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    team_id = payload.get("team", {}).get("id", "")
    user_id = payload.get("user", {}).get("id", "")

    logger.warning("BIA upload modal submission: team=%s channel=%s meta_raw=%r", team_id, channel_id, view.get("private_metadata"))

    values = view.get("state", {}).get("values", {})
    logger.warning("BIA upload modal values keys: %r", list(values.keys()))
    files = values.get("file_block", {}).get("file", {}).get("files", [])
    if not files:
        logger.warning("BIA upload modal: no files in submission, full values=%r", values)
        _warn(channel_id, bot_token, "No file was picked up from the upload dialog -- please try again and make sure the file finishes uploading (shows a thumbnail) before clicking Upload.")
        return
    if not bot_token:
        logger.warning("BIA upload modal: no bot_token for team %s", team_id)
        return

    file_id = files[0].get("id", "")
    if not file_id:
        _warn(channel_id, bot_token, "The upload dialog didn't return a usable file -- please try again.")
        return

    # A file just uploaded through file_input can briefly not be readable
    # yet via files.info (confirmed Slack timing quirk) -- Slack still
    # returns HTTP 200 with {"ok": false, ...} in that case, which
    # raise_for_status() alone wouldn't catch, so check "ok" explicitly.
    # A couple of short retries covers the usual propagation delay.
    slack_file = None
    last_error = ""
    for attempt in range(3):
        if attempt:
            time.sleep(1.5)
        try:
            resp = requests.get(
                f"{SLACK_API_BASE}/files.info",
                headers={"Authorization": f"Bearer {bot_token}"},
                params={"file": file_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if data.get("ok"):
            slack_file = data.get("file")
            break
        last_error = data.get("error", "unknown error")

    if not slack_file:
        logger.warning("Couldn't fetch uploaded file %s after retries: %s", file_id, last_error)
        if channel_id and bot_token:
            try:
                requests.post(
                    f"{SLACK_API_BASE}/chat.postMessage",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    json={"channel": channel_id, "text": f":warning: Couldn't read the uploaded file ({last_error}) -- try uploading again."},
                    timeout=10,
                )
            except requests.RequestException:
                logger.exception("Couldn't post upload-failure message")
        return

    ingest_one_file(slack_file, channel_id, user_id, team_id, bot_token, post_confirmation=False)

    # The modal has no response_url of its own (unlike a block action) --
    # push a fresh status card back into the original BIA Upload message
    # so the admin doesn't have to click "Check again" manually to see
    # the file that just finished uploading.
    if channel_id and message_ts and team_id:
        from .bia_upload_v2_data import build_bia_upload_card
        from .nav_v2 import with_nav_bar_v2

        card = with_nav_bar_v2(build_bia_upload_card(team_id), "bia_upload")
        try:
            requests.post(
                f"{SLACK_API_BASE}/chat.update",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel_id, "ts": message_ts, **card},
                timeout=10,
            )
        except requests.RequestException:
            logger.exception("Couldn't refresh BIA upload card after upload")
