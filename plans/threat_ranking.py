"""
A18 -- ranks the Threat Profile catalog (cards/threats_v2_data.py's
THREATS) against this organization's REAL critical services (from the
resilience map, Phase 1), instead of the same fixed healthcare-company
story shown to every workspace. The threat categories themselves
(Ransomware/External attacker, Insider, etc.) stay the same -- they're
generic and apply to any company -- only the criticality and the "why"
text change, now pointing at real services with real RTOs.

Falls back to the catalog's own original "why"/"default_crit" untouched
if there's no resilience map yet (shouldn't normally happen -- Teams &
Roles, which comes right before this step, already requires a plan to
have been uploaded -- but never invent a fake story if there's truly
nothing real to point to).
"""

import re

# Loose keyword match for which real services a Privacy-module threat
# would actually hit -- a BIA doesn't explicitly say "this service holds
# personal data", so this is a best-effort signal, not a certainty.
_PRIVACY_KEYWORDS = (
    "customer", "patient", "client", "member", "employee", "staff", "personal",
    "pii", "kyc", "hr", "payroll", "health", "record",
)

_HOUR_UNITS = {"hour": 1, "hours": 1, "day": 24, "days": 24, "week": 168, "weeks": 168, "month": 720, "months": 720}


def _rto_to_hours(rto_text: str) -> float | None:
    """Best-effort parse of a free-text RTO ("4 hours", "1 week") into
    hours, for ranking only -- returns None if it can't be read, which
    just drops that service out of the criticality comparison rather
    than guessing a number."""
    if not rto_text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|day|days|week|weeks|month|months)", rto_text.lower())
    if not match:
        return None
    value, unit = match.groups()
    return float(value) * _HOUR_UNITS[unit]


def _criticality_score(hours: float | None) -> float:
    """Shorter RTO = more critical = higher score. Unscored (no RTO
    found) services still count, just at the lowest tier, so they're
    never silently dropped from ranking entirely."""
    if hours is None:
        return 0.5
    if hours <= 4:
        return 3.0
    if hours <= 24:
        return 2.0
    if hours <= 168:
        return 1.0
    return 0.5


def _score_to_crit(score: float) -> str:
    if score >= 2.5:
        return "Critical"
    if score >= 1.5:
        return "High"
    return "Med"


def _is_privacy_relevant(service: dict) -> bool:
    haystack = " ".join(
        [
            service.get("name", ""),
            service.get("impact_if_disrupted", ""),
            " ".join(service.get("dependencies", []) or []),
        ]
    ).lower()
    return any(kw in haystack for kw in _PRIVACY_KEYWORDS)


def sector_research_context(team_id: str) -> str:
    """
    A10/A3 -- one line of real, sector-specific threat/regulator context
    from the 6-agent research (plans/draft_generation.py's draft_research_items),
    shown once at the top of Threat Profile. Separate from rank_threats'
    per-threat RTO-driven "why" text below -- this is the sector-level
    "what's actually hitting companies like yours, and who you answer
    to" context the RTO numbers alone don't carry. Empty string if no
    plan has this (a real uploaded document never does -- only an
    ai_draft plan does, see plans/draft_generation.py).
    """
    from .models import Plan

    plan = (
        Plan.objects(slack_team_id=team_id, is_latest=True, draft_research_items__ne=[])
        .order_by("-created_at")
        .first()
        if team_id
        else None
    )
    if not plan:
        return ""

    items = {i.get("id"): i for i in (plan.draft_research_items or [])}

    def _value_if_title_matches(item_id: str, title_keywords: tuple) -> str:
        """The crew's own structural check only verifies every A1-A12/
        B1-B7 id is present once -- not that each id's CONTENT actually
        matches its own label. Confirmed live: one real run put A12's
        "default tolerance bands" content under the A10 id. Guard
        against showing a mislabeled item by sanity-checking its own
        title before trusting its value."""
        item = items.get(item_id) or {}
        title = (item.get("title") or "").lower()
        if not any(kw in title for kw in title_keywords):
            return ""
        return (item.get("value") or "").strip()

    threat_landscape = _value_if_title_matches("A10", ("threat", "scenario"))
    regulators = _value_if_title_matches("A3", ("regulat", "law", "framework"))
    if not threat_landscape and not regulators:
        return ""

    parts = []
    if threat_landscape and threat_landscape.lower() != "not found":
        parts.append(f"Sector threat landscape: {threat_landscape[:280]}")
    if regulators and regulators.lower() != "not found":
        parts.append(f"Likely applicable regulators: {regulators[:200]}")
    return "\n".join(parts)


def rank_threats(team_id: str, base_threats: list[dict]) -> list[dict]:
    """
    Returns a copy of base_threats, re-sorted and with "why"/"default_crit"
    replaced using the team's real resilience map -- or the list
    unchanged if there's no real plan to rank against yet.
    """
    from .models import Plan

    plan = Plan.objects(slack_team_id=team_id, resilience_map__ne=None).order_by("-created_at").first()
    services = (plan.resilience_map or {}).get("services", []) if plan else []
    if not services:
        return list(base_threats)

    scored = []
    for svc in services:
        hours = _rto_to_hours(svc.get("rto", ""))
        scored.append({"service": svc, "hours": hours, "score": _criticality_score(hours)})
    scored.sort(key=lambda s: s["score"], reverse=True)

    cyber_pool = scored  # any critical service is exposure for a cyber threat
    privacy_pool = [s for s in scored if _is_privacy_relevant(s["service"])] or scored

    ranked = []
    for t in base_threats:
        pool = privacy_pool if t["module"] == "Privacy" else cyber_pool
        top = pool[:3]
        if not top:
            ranked.append(dict(t))
            continue

        avg_score = sum(s["score"] for s in top) / len(top)
        names = [s["service"].get("name", "") for s in top if s["service"].get("name")]
        fastest = min((s["hours"] for s in top if s["hours"] is not None), default=None)

        updated = dict(t)
        updated["default_crit"] = _score_to_crit(avg_score)
        if names:
            rto_bit = f", the fastest with an RTO of {fastest:.0f} hours" if fastest is not None else ""
            updated["why"] = f"Your plan shows this would hit {', '.join(names)}{rto_bit} -- real recovery targets from your uploaded plan, not a sample."
        ranked.append(updated)

    ranked.sort(key=lambda t: {"Critical": 0, "High": 1, "Med": 2}.get(t["default_crit"], 3))
    return ranked
