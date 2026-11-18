"""
"Agent 1.5" -- the real middle step in the Agent 1 -> Agent 1.5 -> Agent
2 pipeline (sir's naming, and an accurate one): takes a threat Agent 1
(threat_profile_generator.py) already produced and approved, plus this
org's real BIA/BCP services/RTOs, and breaks it down into the Incident
and Cause specific to THIS organization -- not a generic industry
guess. This is the piece that's missing for any AI-generated or
admin-added threat otherwise: cards/threat_map_v2_data.py's fixed
THREAT_MAP only has incidents/causes for the old 4 hardcoded threats
(ext/ins/breach/rights), so any new threat would hit "No incidents
mapped for this threat yet." on the Threat Profile screen without this.

Same shape as that fixed map (per threat: a list of incidents, each
with an id/name and a list of causes, each with an id/name), so the
existing drill-down UI (cards/threats_v2_data.py's build_org_threats_card)
can show either one without caring which produced it. Agent 2
(scenario_generator.py) is the next and final step -- it takes
whichever Incident/Cause this produces, plus the same real
services/RTOs and real assigned roles, and writes the actual scenario
and decision questions.

Same NVIDIA-first, Gemini-fallback discipline as the other two agents.
Returns None (never raises) if both AI calls fail -- the caller is
expected to cache a successful result so this only runs once per
threat, not on every click.
"""

import json
import logging
import re

from .nvidia_client import generate

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a cybersecurity and privacy risk analyst. You break one named threat down into the "
    "realistic incidents that threat could actually cause, and the realistic root causes of each "
    "incident -- for use in an incident-response tabletop drill. Respond with ONLY a single JSON "
    "object, no markdown fences, no other text."
)

_PROMPT_TEMPLATE = """Break this threat down for a tabletop drill.

Threat: {label}
Module: {module}
Why this threat applies to this organization: {why}

The organization's real critical processes/systems (from their BIA/BCP) -- prefer incidents \
and causes that would realistically hit one of THESE specific things over a generic industry \
example, whenever one plausibly fits this threat:
{services_block}

List exactly 2 realistic incidents this threat could cause, each with exactly 2 realistic root \
causes. Keep names short (a few words), like a real incident-response taxonomy entry.

For each cause, also write a short awareness note for the team being drilled: "what" (1-2 plain \
sentences explaining what this cause actually is, for someone non-technical) and "why" (1 sentence \
on why it matters / how it actually happens in practice). Same spirit as a security-awareness \
training card -- concrete and specific to this cause, not generic advice.

Return a JSON object shaped exactly like this:

{{
  "incidents": [
    {{
      "id": "<short unique slug, e.g. ransom_outbreak>",
      "name": "<short incident name, e.g. Ransomware outbreak>",
      "causes": [
        {{"id": "<short unique slug>", "name": "<short cause name>", "what": "<1-2 plain sentences>", "why": "<1 sentence>"}},
        {{"id": "<short unique slug>", "name": "<short cause name>", "what": "<1-2 plain sentences>", "why": "<1 sentence>"}}
      ]
    }}
  ]
}}
"""


def generate_threat_map(label: str, module: str, why: str, team_id: str = "") -> list[dict] | None:
    """
    Returns [{"id","name","causes":[{"id","name"}, ...]}] for this one
    threat, or None if both AI providers failed.

    Confirmed live (admin feedback): generating Incident/Cause from
    just the threat's own label/why, with no visibility into the
    org's real BIA/BCP data, risked incidents/causes that felt
    disconnected from that specific organization -- same real services
    Agent 2 (scenario_generator.py) already reads are passed in here
    too now, so Incident/Cause can name real critical processes
    whenever one plausibly fits, instead of staying generic.
    """
    services_block = "Not available -- no BIA/BCP uploaded yet, or no real services on file."
    if team_id:
        from .models import Plan

        plan = Plan.objects(slack_team_id=team_id, resilience_map__ne=None).order_by("-created_at").first()
        services = (plan.resilience_map or {}).get("services", []) if plan else []
        if services:
            services_block = "\n".join(f"- {s.get('name', '?')} (RTO {s.get('rto', 'unknown')})" for s in services[:10])

    prompt = _PROMPT_TEMPLATE.format(label=label, module=module, why=why or "not specified", services_block=services_block)

    raw = generate(prompt, system=_SYSTEM_PROMPT, max_tokens=2048, temperature=0.4)
    incidents = _parse_json_response(raw) if raw is not None else None

    if incidents is None:
        logger.warning("NVIDIA threat-map generation failed or returned unparseable data for %r -- falling back to Gemini", label)
        from .gemini_client import generate as gemini_generate

        raw = gemini_generate(f"{_SYSTEM_PROMPT}\n\n{prompt}")
        incidents = _parse_json_response(raw) if raw is not None else None

    return incidents


def _parse_json_response(raw_text: str) -> list[dict] | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Could not parse threat-map response as JSON: %s", raw_text[:500])
        return None
    if not isinstance(data, dict):
        return None

    incidents = data.get("incidents")
    if not isinstance(incidents, list) or not incidents:
        return None

    cleaned_incidents = []
    seen_ids = set()
    for inc in incidents:
        if not isinstance(inc, dict):
            continue
        inc_id = (inc.get("id") or "").strip().lower().replace(" ", "_")
        inc_name = (inc.get("name") or "").strip()
        if not inc_id or not inc_name or inc_id in seen_ids:
            continue
        seen_ids.add(inc_id)

        causes = []
        seen_cause_ids = set()
        for c in inc.get("causes") or []:
            if not isinstance(c, dict):
                continue
            c_id = (c.get("id") or "").strip().lower().replace(" ", "_")
            c_name = (c.get("name") or "").strip()
            if not c_id or not c_name or c_id in seen_cause_ids:
                continue
            seen_cause_ids.add(c_id)
            causes.append(
                {
                    "id": c_id,
                    "name": c_name,
                    "what": (c.get("what") or "").strip(),
                    "why": (c.get("why") or "").strip(),
                }
            )

        if causes:
            cleaned_incidents.append({"id": inc_id, "name": inc_name, "causes": causes})

    return cleaned_incidents or None
