"""
Incident-wide testing (sir's call): the org should test by INCIDENT, not
by picking one Cause at a time -- ALL causes under the chosen Incident
are given to the AI together as context, and it writes ONE scenario that
covers the incident as a whole.

This used to write a FULL separate scenario per cause (8 questions each)
and glue them end to end -- 2 causes = 16 questions, 6 causes = 48,
impossible for a real person to sit through. One single generation call
now covers every cause, with the total question count capped by
plans.scenario_generator.target_question_count (scales gently with how
many causes there really are, never multiplies).
"""

import logging

from .models_v2 import GeneratedScenario

logger = logging.getLogger(__name__)


def send_awareness_dms(team_id: str, module: str, threat_key: str, incident_id: str, causes: list, bot_token: str) -> int:
    """
    Awareness is only real awareness if the whole team sees it, not just
    the admin who clicked (sir's call) -- DMs every real staffed team
    member (any role, any team), not a single group-channel post, each
    in their own conversation with the TestMyPlan app. Instant -- the
    what/why per cause is already written and cached (Agent 1.5 /
    cards/cause_awareness_modal_v2.py's fixed taxonomy), no AI call here
    -- so this can run right before the slower scenario generation on
    the same click without adding any real wait. Returns how many people
    were actually reached.
    """
    from django.conf import settings

    from .awareness_card_image import get_awareness_card_image_url, icon_key_for
    from .cause_awareness_modal_v2 import CAUSE_AWARENESS
    from .models_v2 import Team, TeamMember
    from .slack_client import SlackApiError, _call
    from .threat_profile_review_v2 import resolve_names

    if not causes or not bot_token:
        return 0

    _, incident_name, _ = resolve_names(team_id, module, threat_key, incident_id, causes[0]["id"])

    # Rendered as a real image (sir's "Before it's tested" design) --
    # same template-code approach as the other cards. The reference
    # design shows ONE flowing description per cause, not separate
    # "What it is" / "Why it matters" labels, so what+why are joined
    # into one sentence here.
    card_causes: list[tuple[str, str, str]] = []
    for cause in causes:
        cause_id = cause.get("id", "")
        cause_name = cause.get("name", cause_id)
        fixed = CAUSE_AWARENESS.get(cause_id)
        if fixed:
            fixed_emoji, what, why = fixed.get("icon", ""), fixed.get("what", ""), fixed.get("why", "")
        else:
            fixed_emoji, what, why = "", cause.get("what", ""), cause.get("why", "")
        description = f"{what} {why}".strip() if what and why else (what or why)
        card_causes.append((cause_name, description, icon_key_for(cause_name, fixed_emoji)))

    image_url = get_awareness_card_image_url(settings.BACKEND_URL, incident_name, card_causes)
    blocks = [{"type": "image", "image_url": image_url, "alt_text": f"Awareness — {incident_name}"}]

    sent_to = set()
    for team_doc in Team.objects(team_id=team_id):
        for tm in TeamMember.objects(team=team_doc):
            recipient = tm.primary_slack_user_ids[0] if tm.primary_slack_user_ids else ""
            if not recipient or recipient in sent_to:
                continue
            try:
                opened = _call("conversations.open", bot_token, users=recipient)
                dm_channel_id = opened["channel"]["id"]
                _call("chat.postMessage", bot_token, channel=dm_channel_id, text=f"Awareness: {incident_name}", blocks=blocks)
                sent_to.add(recipient)
            except SlackApiError:
                logger.exception("Incident awareness: failed to DM %s", recipient)
    return len(sent_to)


def get_or_generate_incident_scenario(
    team_id: str, module: str, threat_key: str, incident_id: str, causes: list,
) -> "GeneratedScenario | None":
    """
    Returns the existing combined (all-causes) scenario for this Incident
    if one's already been generated, otherwise writes one now with a
    single AI call covering every cause together. Returns None if the AI
    call fails outright.
    """
    existing = (
        GeneratedScenario.objects(
            team_id=team_id, module=module, threat_id=threat_key, incident_id=incident_id, cause_id="",
        )
        .order_by("-created_at")
        .first()
        if team_id
        else None
    )
    if existing:
        return existing

    from .threat_profile_review_v2 import resolve_names
    from plans.scenario_generator import FULL_LIFECYCLE_PHASES, generate_scenario, target_question_range

    cause_names = []
    for cause in causes:
        _, _, cause_name = resolve_names(team_id, module, threat_key, incident_id, cause["id"])
        cause_names.append(cause_name or cause["id"])

    threat_label, incident_name, _ = resolve_names(team_id, module, threat_key, incident_id, causes[0]["id"] if causes else "")
    combined_cause_text = "; ".join(cause_names) if len(cause_names) > 1 else (cause_names[0] if cause_names else "")

    min_target, total_target = target_question_range(len(causes))
    result = generate_scenario(
        team_id, threat_label, incident_name, combined_cause_text, FULL_LIFECYCLE_PHASES,
        total_target=total_target, min_target=min_target,
    )
    if result and result.get("error") == "missing_plan_or_roles":
        logger.warning("Incident test: no real plan/roles for incident %s", incident_id)
        return "missing_plan_or_roles"

    if not result or not result.get("injects"):
        logger.warning("Incident test: couldn't write a combined scenario for incident %s", incident_id)
        return None

    combined = GeneratedScenario(
        team_id=team_id, module=module, threat_id=threat_key, incident_id=incident_id, cause_id="",
        threat_label=threat_label, incident_name=incident_name, cause_name=" + ".join(cause_names),
        phases=FULL_LIFECYCLE_PHASES,
        injects=result["injects"], consequence_injects=result.get("consequence_injects", []),
    )
    combined.save()
    return combined
