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

_HOUR_UNITS = {
    "hour": 1, "hours": 1, "hr": 1, "hrs": 1,
    "minute": 1 / 60, "minutes": 1 / 60, "min": 1 / 60, "mins": 1 / 60,
    "day": 24, "days": 24,
    "week": 168, "weeks": 168,
    "month": 720, "months": 720,
}


def _rto_to_hours(rto_text: str) -> float | None:
    """Best-effort parse of a free-text RTO ("4 hours", "1 week") into
    hours, for ranking only -- returns None if it can't be read, which
    just drops that service out of the criticality comparison rather
    than guessing a number.

    Confirmed live against a real document: the original version only
    matched the full words "hour(s)"/"day(s)"/"week(s)"/"month(s)" --
    real documents also write "4 Hrs", "15 minutes", and "Immediate",
    none of which matched, so those services silently sorted to the
    bottom (unknown) instead of near the top (most urgent) wherever
    this function's result is used for sorting/ranking."""
    if not rto_text:
        return None
    t = rto_text.lower()
    if "immediate" in t or "near zero" in t or "real-time" in t or "real time" in t or "asap" in t:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|hrs|hr\b|minute|minutes|mins|min\b|day|days|week|weeks|month|months)", t)
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


_STOPWORDS = frozenset(
    "the a an of to for and or with on in at from by is are this that threat attack risk "
    "compromise failure breach incident outage misconfiguration exposure tampering unauthorized".split()
)


def _keywords(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3 and w not in _STOPWORDS}


def mapped_services_for_threat(team_id: str, threat: dict, require_real_match: bool = False) -> list[dict]:
    """
    Which real BIA/BCP services this specific threat would actually hit
    -- shown under a selected threat so "why critical" isn't just text,
    it points at real named services. Matched by real keyword overlap
    between the threat's own label/why and each service's name/category/
    dependencies, not the same module-wide top-3 every threat in
    rank_threats() used to get (that was the bug reported live: every
    threat in a module showed the identical "why" sentence because the
    top-3 pool doesn't vary per threat, only per module).

    Falls back to the module's most time-critical services (lowest RTO)
    only if no real keyword overlap is found at all -- still better
    than nothing, but never pretends a guess is a real match.
    Returns [] if there's no uploaded plan yet.
    """
    from .models import Plan

    plan = Plan.objects(slack_team_id=team_id, resilience_map__ne=None).order_by("-created_at").first() if team_id else None
    services = (plan.resilience_map or {}).get("services", []) if plan else []
    if not services:
        return []

    threat_kw = _keywords(threat.get("label", "")) | _keywords(threat.get("why", ""))
    pool = services
    if threat.get("module") == "Privacy":
        privacy_pool = [s for s in services if _is_privacy_relevant(s)]
        pool = privacy_pool or services

    scored = []
    for svc in pool:
        svc_kw = _keywords(svc.get("name", "")) | _keywords(svc.get("category", "")) | _keywords(" ".join(svc.get("dependencies", []) or []))
        overlap = len(threat_kw & svc_kw)
        if overlap:
            scored.append((overlap, svc))

    if scored:
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [svc for _, svc in scored[:3]]

    if require_real_match:
        # Caller is using this to SCORE severity, not to display a
        # name -- a guessed fallback must never count as real evidence
        # for a rating. This was still happening even after the first
        # fix: with no genuine keyword overlap, every threat fell back
        # to the same module-wide fastest-RTO services, so every threat
        # was still scored identically and bumped to Critical again,
        # just through this fallback path instead of the original one.
        return []

    # Display-only fallback -- no real keyword overlap, but still show
    # the pool's most time-critical services rather than nothing.
    fallback = sorted(pool, key=lambda s: _criticality_score(_rto_to_hours(s.get("rto", ""))), reverse=True)
    return fallback[:3]


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

    ranked = []
    for t in base_threats:
        # Score THIS threat's own real-matched services (same keyword
        # overlap mapped_services_for_threat already uses), not a
        # module-wide top-3 -- that used to be the same fixed pool for
        # every threat in a module, so every Cybersecurity threat (or
        # every Privacy one) got bumped to the exact same "Critical",
        # overwriting Agent 1's real spread entirely. Confirmed live:
        # reported as "why is everything Critical in Threat Mapping when
        # Threat Approval correctly shows a High/Med spread for the same
        # threats" -- Threat Approval reads Agent 1's own rating
        # untouched; this function was the one silently flattening it.
        matched = mapped_services_for_threat(team_id, t, require_real_match=True)
        if not matched:
            ranked.append(dict(t))
            continue

        scores = [_criticality_score(_rto_to_hours(s.get("rto", ""))) for s in matched]
        avg_score = sum(scores) / len(scores)

        updated = dict(t)
        # Only use the real data to raise a rating Agent 1 under-called,
        # never to lower one it already called Critical/High from the
        # sign-up profile alone -- a threat the AI already flagged as
        # the top concern shouldn't get silently downgraded just because
        # its matched services happen to have a longer RTO.
        from_services = _score_to_crit(avg_score)
        rank_order = {"Critical": 0, "High": 1, "Med": 2}
        if rank_order.get(from_services, 2) < rank_order.get(t.get("default_crit", "Med"), 2):
            updated["default_crit"] = from_services
        # "why" is left untouched -- it's Agent 1's per-threat reasoning.
        ranked.append(updated)

    ranked.sort(key=lambda t: {"Critical": 0, "High": 1, "Med": 2}.get(t["default_crit"], 3))
    return ranked
