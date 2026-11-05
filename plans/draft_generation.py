"""
"No BCP, don't want GRC" path -- runs the separate ir_onboarding_crew
tool (its own venv, its own dependencies, NOT installed into this
project) as a subprocess, and turns its output into a real Plan, in the
same resilience_map shape an uploaded document produces, so it flows
through the exact same Upload & Analysis / Approve screen.

Triggered from cards.interactivity_v2's v2_bia_generate_draft handler,
in a background thread (same pattern as a DM upload in home_tab/views.py).
"""

import io
import json
import logging
import os
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Real research with real web calls -- generously bounded, not expected
# to be hit (live-tested run took 2-4 minutes).
_TIMEOUT_SECONDS = 900

# Maps a LiteLLM model-string provider prefix ("gemini/...", "openai/...")
# to the API key env var CrewAI's LLM expects for it -- lets the fallback
# logic below work no matter which provider is primary vs backup.
_PROVIDER_API_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _build_docx(session_prefill_text: str) -> bytes:
    import docx

    doc = docx.Document()
    for line in session_prefill_text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _parse_env_file(path: Path) -> dict:
    """Minimal KEY=VALUE .env reader -- avoids adding python-dotenv as a
    dependency of this Django project just to read two values out of
    the crew's own .env file."""
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def _run_crew_subprocess(org_name: str, website_url: str, country: str, sector_hint: str, model_env: dict) -> subprocess.CompletedProcess:
    """One real subprocess run of the crew. model_env overrides MODEL
    (and whatever key that model needs) on top of the crew's own .env --
    python-dotenv's load_dotenv() never overrides an already-set env var,
    so this reliably wins over the .env file's default MODEL."""
    crew_dir = Path(settings.ONBOARDING_CREW_DIR)
    crew_python = crew_dir / ".venv" / "Scripts" / "python.exe"
    return subprocess.run(
        [
            str(crew_python), "-m", "onboarding_crew.main",
            "--company", org_name, "--website", website_url,
            "--country", country, "--sector-hint", sector_hint,
        ],
        cwd=str(crew_dir),
        capture_output=True,
        text=True,
        # The child writes UTF-8 (PYTHONIOENCODING below), but
        # subprocess.run's own default text-decoding uses THIS process's
        # locale (cp1252 on this Windows box), which can't decode some
        # characters the crew's own event logging emits -- confirmed
        # live: a UnicodeDecodeError here corrupted the failure path
        # itself (result.stdout came back None), not just cosmetic.
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_SECONDS,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", **model_env},
    )


def run_draft_generation(team_id: str) -> tuple[bool, str]:
    """Runs the crew for team_id's org, saves a real Plan from its
    output. Returns (success, error_message) -- error_message is "" on
    success. Never raises -- caller logs/ignores. Also responsible for
    setting DraftBiaRequest's final status/error_message itself, since
    this is the one place that knows exactly which step failed and why.

    Tries whichever provider the crew's own .env has as MODEL first; if
    that run fails outright (quota, outage, crash -- anything, since by
    the time we're here the research is worth more than being picky
    about which provider broke), retries once with FALLBACK_MODEL from
    that same .env file. This file deliberately never hardcodes which
    provider is primary vs fallback, or any model name/key itself --
    that's all read live from the crew's .env, so sir can swap the
    order there without any code change here."""
    from cards.models_v2 import DraftBiaRequest, OrgProfile
    from plans.models import STATUS_PARSED, Plan

    def _fail(message: str, log_detail: str = "") -> tuple[bool, str]:
        logger.error("Draft generation failed for team %s: %s %s", team_id, message, log_detail[-2000:])
        if team_id:
            DraftBiaRequest.objects(team_id=team_id).update(set__status="failed", set__error_message=message)
        return False, message

    profile = OrgProfile.objects(team_id=team_id).first() if team_id else None
    org_name = (profile.org_name if profile else "") or "Unknown Organization"
    website_url = (profile.website_url if profile else "") or "unknown"
    country = (profile.regions[0] if profile and profile.regions else "") or "unknown"
    sector_hint = (profile.industry if profile else "") or "unknown"

    crew_dir = Path(settings.ONBOARDING_CREW_DIR)

    try:
        result = _run_crew_subprocess(org_name, website_url, country, sector_hint, {})
        timed_out = False
    except subprocess.TimeoutExpired:
        result, timed_out = None, True
    except Exception as exc:
        return _fail("Research couldn't start (a system error, not your company's fault).", str(exc))

    if timed_out or result.returncode != 0:
        first_detail = "(timed out)" if timed_out else ((result.stdout or "") + (result.stderr or ""))
        logger.warning("Primary model run failed for team %s, retrying with fallback model: %s", team_id, first_detail[-500:])

        crew_env = _parse_env_file(crew_dir / ".env")
        fallback_model = crew_env.get("FALLBACK_MODEL", "")
        # Provider-agnostic on purpose: whichever provider is primary
        # today (openai/gemini/anthropic/...) could be the fallback
        # tomorrow if sir swaps the order again -- infer the right API
        # key env var from the fallback model's own prefix instead of
        # assuming it's always OpenAI.
        fallback_key_name = _PROVIDER_API_KEY_ENV.get(fallback_model.split("/", 1)[0], "")
        fallback_key = crew_env.get(fallback_key_name, "")
        if not fallback_model or not fallback_key_name or not fallback_key:
            return _fail(
                "Research failed with the primary AI provider, and no backup provider is configured.",
                first_detail,
            )

        try:
            result = _run_crew_subprocess(
                org_name, website_url, country, sector_hint,
                {"MODEL": fallback_model, fallback_key_name: fallback_key},
            )
        except subprocess.TimeoutExpired:
            return _fail(f"Research took longer than {_TIMEOUT_SECONDS // 60} minutes and was stopped, even after retrying with a backup provider.")
        except Exception as exc:
            return _fail("Research couldn't start (a system error, not your company's fault).", str(exc))

        if result.returncode != 0:
            return _fail(
                "Research hit an error partway through, with both the primary and backup AI provider.",
                (result.stdout or "") + (result.stderr or ""),
            )

    try:
        data = json.loads((crew_dir / "output" / "draft_context_profile.json").read_text(encoding="utf-8"))
        session_text = (crew_dir / "output" / "session_prefill.md").read_text(encoding="utf-8")
    except Exception as exc:
        return _fail("Research finished but its output couldn't be read.", str(exc))

    candidate_services = data.get("candidate_services", [])
    if not candidate_services:
        return _fail(
            "Research didn't find enough public information about this organization to propose anything. "
            "Try DMing a real document instead, or check the website on file is correct."
        )

    services = [
        {
            "name": s.get("service", "") or "Unnamed service",
            "rto": s.get("proposed_rto", "") or "not stated",
            "source": "AI-generated draft research (not a client-provided document)",
        }
        for s in candidate_services
    ]

    Plan.objects(slack_team_id=team_id, is_latest=True).update(is_latest=False)

    plan = Plan(
        filename=f"AI-generated draft BIA - {org_name}.docx",
        file_extension="docx",
        slack_team_id=team_id,
        version=1,
        is_latest=True,
        status=STATUS_PARSED,
        generation_source="ai_draft",
        draft_research_items=data.get("items", []),
    )
    plan.file_data.put(
        _build_docx(session_text),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    plan.resilience_map = {"services": services, "candidate_services_full": candidate_services}
    plan.save()

    if team_id:
        DraftBiaRequest.objects(team_id=team_id).update(set__status="completed", set__error_message="")
    return True, ""


def run_draft_generation_then_refresh(team_id: str, bot_token: str) -> None:
    """Background-thread entry point: runs the crew, then pushes a fresh
    Upload & Analysis card (success OR failure state) to wherever that
    screen was last shown, same push mechanism home_tab/views.py already
    uses after a DM upload."""
    try:
        run_draft_generation(team_id)
    except Exception:
        logger.exception("Unexpected error generating draft BIA for team %s", team_id)
        from cards.models_v2 import DraftBiaRequest

        if team_id:
            DraftBiaRequest.objects(team_id=team_id).update(
                set__status="failed", set__error_message="An unexpected error occurred."
            )

    try:
        from cards.bia_upload_v2_data import build_bia_upload_card, build_draft_failed_card
        from cards.models_v2 import DraftBiaRequest
        from cards.nav_v2 import with_nav_bar_v2
        from cards.persistence_v2 import load_bia_upload_card_location
        from cards.slack_client import SlackApiError, _call

        failed = DraftBiaRequest.objects(team_id=team_id, status="failed").first() if team_id else None
        card_blocks = build_draft_failed_card(team_id) if failed else build_bia_upload_card(team_id)

        location = load_bia_upload_card_location(team_id)
        channel_id, message_ts = location.get("channel_id", ""), location.get("message_ts", "")
        if channel_id and message_ts and bot_token:
            card = with_nav_bar_v2(card_blocks, "bia_upload")
            _call("chat.update", bot_token, channel=channel_id, ts=message_ts, **card)
    except SlackApiError:
        logger.exception("Couldn't refresh Upload & Analysis card after draft generation for team %s", team_id)
    except Exception:
        logger.exception("Unexpected error refreshing Upload & Analysis card for team %s", team_id)
