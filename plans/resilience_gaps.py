"""
Phase 1 (Read) -- A11: find gaps/conflicts in the extracted resilience
map before the admin can lock in the objectives register (A12). Plain
rule checks, not AI -- the kind of thing a human reviewer would
immediately flag, matching the real examples named in sir's proposal:
a service with no RTO/RPO, a role with no backup, a plan not reviewed
in 12 months, and conflicting numbers between two documents.
"""

import datetime
import logging

logger = logging.getLogger(__name__)

_STALE_PLAN_MONTHS = 12


def other_resilience_maps_for_team(team_id: str, exclude_plan_id=None) -> list:
    """Every other real uploaded plan's resilience map for this
    workspace, for the cross-document conflict check -- excludes the
    plan currently being reviewed."""
    from .models import Plan

    qs = Plan.objects(slack_team_id=team_id, resilience_map__ne=None)
    if exclude_plan_id:
        qs = qs.filter(id__ne=exclude_plan_id)
    return [p.resilience_map for p in qs if p.resilience_map]


def suggested_teams_and_roles(team_id: str) -> dict:
    """
    A13/A14 -- what the plan's resilience map named as response teams and
    roles, for a read-only "Suggested from your plan" list on the Teams &
    Roles step. The admin decides whether/where to add each one by hand
    (via the normal catalog pickers) -- this never auto-adds anything,
    since the 35-team cyber catalog and a BIA/BCP's own team/role names
    don't line up closely enough to match automatically without risking
    a wrong guess.
    """
    from .models import Plan

    plan = Plan.objects(slack_team_id=team_id, resilience_map__ne=None).order_by("-created_at").first()
    if not plan or not plan.resilience_map:
        return {"teams": [], "roles": []}

    rmap = plan.resilience_map
    teams = [t.get("name", "").strip() for t in rmap.get("response_teams", []) if t.get("name")]
    roles = [
        {"title": r.get("title", "").strip(), "has_backup": bool(r.get("has_backup"))}
        for r in rmap.get("roles", [])
        if r.get("title")
    ]
    return {"teams": teams, "roles": roles}


def find_resilience_gaps(resilience_map: dict, *, other_plans: list | None = None) -> list[dict]:
    """
    Returns [{"service": "<name>", "issue": "<what's missing>"}, ...].
    Empty list means nothing to flag -- A12 can proceed straight away.

    `other_plans` -- other real Plan documents already uploaded for the
    same workspace (resilience_map dicts), to check for conflicting
    numbers on the same service across documents. Optional: the basic
    per-document checks below still run without it.
    """
    resilience_map = resilience_map or {}
    gaps = []

    for svc in resilience_map.get("services", []):
        name = svc.get("name") or "Unnamed service"
        if not svc.get("rto"):
            gaps.append({"service": name, "issue": "No RTO (recovery time objective) found for this service."})
        if not svc.get("rpo"):
            gaps.append({"service": name, "issue": "No RPO (recovery point objective) found for this service."})
        if not svc.get("dependencies"):
            gaps.append({"service": name, "issue": "No dependencies listed -- may be incomplete, worth double-checking."})

    for role in resilience_map.get("roles", []):
        if role.get("has_backup") is False:
            title = role.get("title") or "Unnamed role"
            person = f" ({role['person']})" if role.get("person") else ""
            gaps.append({"service": f"{title}{person}", "issue": "No backup named for this role -- a single point of failure if they're unavailable."})

    stale_issue = _check_stale_plan(resilience_map.get("document_date", ""))
    if stale_issue:
        gaps.append({"service": "Document", "issue": stale_issue})

    if other_plans:
        gaps.extend(_find_cross_document_conflicts(resilience_map, other_plans))

    return gaps


def _check_stale_plan(document_date: str) -> str:
    """Flags a plan whose own stated version/review date is more than
    12 months old. Returns "" if the date is missing or unparseable --
    sir's call: don't flag what we can't confirm, don't guess."""
    if not document_date:
        return ""

    try:
        from dateutil import parser as date_parser

        parsed = date_parser.parse(document_date, default=datetime.datetime(1, 1, 1), fuzzy=True)
        if parsed.year == 1:
            return ""
    except (ValueError, OverflowError, TypeError):
        return ""

    months_old = (datetime.datetime.utcnow().year - parsed.year) * 12 + (datetime.datetime.utcnow().month - parsed.month)
    if months_old >= _STALE_PLAN_MONTHS:
        return f"This plan is dated {document_date} -- over {_STALE_PLAN_MONTHS} months old. May need a fresh review."
    return ""


def _find_cross_document_conflicts(resilience_map: dict, other_plans: list) -> list[dict]:
    """Same service name, different RTO/RPO/MTPD value in another real
    uploaded document for this workspace -- a real contradiction the
    admin needs to resolve, not something we can silently pick a side
    on."""
    conflicts = []
    this_services = {s.get("name", "").strip().lower(): s for s in resilience_map.get("services", []) if s.get("name")}

    for other in other_plans:
        for other_svc in (other or {}).get("services", []):
            key = (other_svc.get("name") or "").strip().lower()
            if key not in this_services:
                continue
            this_svc = this_services[key]
            for field, label in (("rto", "RTO"), ("rpo", "RPO")):
                this_value = this_svc.get(field)
                other_value = other_svc.get(field)
                if this_value and other_value and this_value.strip().lower() != other_value.strip().lower():
                    conflicts.append(
                        {
                            "service": this_svc.get("name"),
                            "issue": f"{label} conflict: this document says \"{this_value}\", another uploaded document says \"{other_value}\".",
                        }
                    )
    return conflicts
